mod config;
mod oauth;

use std::io::{BufRead, BufReader};
use std::path::PathBuf;
use std::process::{Command, Stdio};
use tauri::{Emitter, Manager, WebviewUrl, WebviewWindowBuilder};

// ponytail: dev-only runner; the report is out of scope for the first release
// (`ReportPage` is hidden unless the app is running against a dev config), and
// this is the last spawn left. It goes when the report backend is settled —
// either a PyInstaller sidecar or LangGraph.js — and `repo_root()` goes with it.
const REPORT_CMD: &[&str] = &["uv", "run", "python", "-m", "spotify_core.report"];

// The remaining setup steps that still shell out to Python. Each one is a Phase 2
// item; the list shrinks to nothing rather than being replaced.
const CLI_CMD: &[&str] = &["uv", "run", "spotify-mcp"];

/// Repo root, resolved at *compile* time — so anything using this only works on
/// the machine that built it. That is why it may only be reached from the two
/// dev-only spawns below, never from a path a packaged user can take.
fn repo_root() -> PathBuf {
    std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../..")
}

/// Run a `spotify-mcp` subcommand from the repo root and return its stdout.
fn run_cli(args: &[String]) -> Result<String, String> {
    let out = Command::new(CLI_CMD[0])
        .args(&CLI_CMD[1..])
        .args(args)
        .current_dir(repo_root())
        .env("PYTHONUTF8", "1")
        .output()
        .map_err(|e| format!("failed to spawn `{}`: {e}", CLI_CMD[0]))?;
    if out.status.success() {
        Ok(String::from_utf8_lossy(&out.stdout).into_owned())
    } else {
        let err = String::from_utf8_lossy(&out.stderr);
        let tail: Vec<&str> = err.lines().rev().take(12).collect();
        Err(tail.into_iter().rev().collect::<Vec<_>>().join("\n"))
    }
}

/// Effective runtime config as a JSON string; the frontend parses it.
///
/// Reads the config file directly. This used to spawn `uv run spotify-mcp config
/// get`, which cost ~1.7s on every call and could not work in a packaged build.
#[tauri::command]
fn get_config() -> Result<String, String> {
    serde_json::to_string(&config::read()).map_err(|e| e.to_string())
}

/// Upsert `KEY=VALUE` pairs into the config file. Sibling keys — including ones
/// this build does not know about — are left untouched.
/// Callers must tell the user changes apply on restart.
#[tauri::command]
fn set_config(pairs: Vec<String>) -> Result<String, String> {
    let env_file = config::write(&pairs)?;
    Ok(serde_json::json!({ "env_file": env_file, "written": pairs.len() }).to_string())
}

/// Generate `TOKEN_ENCRYPT_KEY` if absent; never rotates an existing one.
/// The key itself is not returned — it would land in the caller's log.
#[tauri::command]
fn keygen() -> Result<String, String> {
    let created = config::ensure_fernet_key()?;
    Ok(serde_json::json!({ "created": created }).to_string())
}

/// The Fernet key, for the frontend to encrypt tokens with before they are sent
/// to the Worker.
///
/// This is the one place a secret crosses into the webview. The alternative —
/// encrypting in Rust — would mean a second Fernet implementation, and the
/// Worker cron has to decrypt exactly what this produces. A disagreement of one
/// byte yields tokens the cron cannot read, and it surfaces hours later in a
/// scheduled run rather than here. Sharing `fernet.ts` with the Worker is the
/// property worth protecting; the webview is local and loads no remote code.
#[tauri::command]
fn encryption_key() -> Result<String, String> {
    config::fernet_key_value().ok_or_else(|| "no TOKEN_ENCRYPT_KEY set".to_string())
}

/// Wait for Spotify's OAuth redirect and return its raw query string.
///
/// Blocking, on the blocking pool: it is idle for as long as the user takes in
/// the browser. The frontend built `authorize_url` and holds the `state` and
/// verifier to check the result against.
#[tauri::command]
async fn await_oauth_callback(authorize_url: String, port: u16) -> Result<String, String> {
    tauri::async_runtime::spawn_blocking(move || oauth::await_callback(&authorize_url, port))
        .await
        .map_err(|e| e.to_string())?
}

/// Run one setup step. Steps are whitelisted rather than taking a command from
/// the frontend, so this stays a fixed surface and not an arbitrary spawn.
///
/// Buffered like `generate_report`: neither step has meaningful intermediate
/// progress, so the UI shows running/done/failed and expands output on failure.
#[tauri::command]
async fn run_setup_step(step: String, arg: Option<String>) -> Result<String, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let args: Vec<String> = match step.as_str() {
            // run_oauth() only prints, never reads stdin — safe to spawn headless.
            // It opens the browser itself and serves the 127.0.0.1:8888 callback.
            "oauth" => vec!["reauth".into()],
            // Fallback for users whose Spotify export has not arrived yet:
            // pulls the last ~50 plays so the dashboard is not empty.
            "sync" => vec!["sync".into()],
            "import" => vec![
                "import-history".into(),
                "--from".into(),
                arg.ok_or("import step requires a path")?,
            ],
            // `keygen` used to be here. It is the `keygen` command now, in Rust:
            // 32 bytes from the OS RNG never needed a Python process.
            other => return Err(format!("unknown setup step: {other}")),
        };
        run_cli(&args)
    })
    .await
    .map_err(|e| e.to_string())?
}

/// Deploy the Cloudflare backend, streaming the log to the Setup page.
///
/// The only spawn here that is not buffered: the deploy takes minutes (D1
/// create, migrations, Worker upload, secret propagation), and a frozen button
/// for that long reads as a hang. Lines go out as `cloud-log` events.
///
/// The GUI deliberately knows nothing about wrangler — it calls one subcommand,
/// so the wrangler → Cloudflare REST swap never reaches this file.
#[tauri::command]
async fn cloud_deploy(
    app: tauri::AppHandle,
    name: String,
    api_token: String,
    rotate: bool,
) -> Result<(), String> {
    tauri::async_runtime::spawn_blocking(move || {
        let mut args: Vec<String> = vec!["cloud".into(), "deploy".into(), "--name".into(), name];
        if !api_token.is_empty() {
            args.push("--api-token".into());
            args.push(api_token);
        }
        if rotate {
            args.push("--rotate".into());
        }

        let mut child = Command::new(CLI_CMD[0])
            .args(&CLI_CMD[1..])
            .args(&args)
            .current_dir(repo_root())
            .env("PYTHONUTF8", "1")
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .map_err(|e| format!("failed to spawn `{}`: {e}", CLI_CMD[0]))?;

        // stderr on its own thread: the deploy interleaves both, and reading
        // them in sequence would deadlock once a pipe buffer fills.
        let stderr = child.stderr.take().map(|err| {
            let app = app.clone();
            std::thread::spawn(move || {
                for line in BufReader::new(err).lines().map_while(Result::ok) {
                    let _ = app.emit("cloud-log", line);
                }
            })
        });
        if let Some(out) = child.stdout.take() {
            for line in BufReader::new(out).lines().map_while(Result::ok) {
                let _ = app.emit("cloud-log", line);
            }
        }
        if let Some(handle) = stderr {
            let _ = handle.join();
        }

        let status = child.wait().map_err(|e| e.to_string())?;
        if status.success() {
            Ok(())
        } else {
            Err("deploy failed — see the log above".to_string())
        }
    })
    .await
    .map_err(|e| e.to_string())?
}

/// Folder picker for the history import. Spotify exports are a directory of
/// `Streaming_History_Audio_*.json`, so this picks the folder, not one file.
#[tauri::command]
async fn pick_history_folder() -> Result<Option<String>, String> {
    tauri::async_runtime::spawn_blocking(|| {
        Ok(rfd::FileDialog::new()
            .pick_folder()
            .map(|p| p.to_string_lossy().into_owned()))
    })
    .await
    .map_err(|e| e.to_string())?
}

// `doctor` used to be a command here, spawning `spotify-mcp doctor --json`.
// It is gone: the config-derived checks ride along in `get_config`'s `checks`
// field (one file read instead of a second ~1.7s process), and the two
// database-derived checks are composed in `lib/config.ts`, which already holds
// an open SQLite handle for the dashboard.

#[tauri::command]
async fn generate_report(
    style: String,
    start: String,
    end: String,
    period_type: String,
    provider: String,
    model: String,
) -> Result<String, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let repo_root = repo_root();
        let out = Command::new(REPORT_CMD[0])
            .args(&REPORT_CMD[1..])
            .args([
                "--style", &style, "--start", &start, "--end", &end,
                "--period-type", &period_type,
                "--provider", &provider, "--model", &model,
                "--no-save",
            ])
            .current_dir(&repo_root)
            .env("PYTHONUTF8", "1")
            .output()
            .map_err(|e| format!("failed to spawn `{}`: {e}", REPORT_CMD[0]))?;
        if out.status.success() {
            Ok(String::from_utf8_lossy(&out.stdout).into_owned())
        } else {
            let err = String::from_utf8_lossy(&out.stderr);
            // Last few lines are the actual Python error; the rest is log noise.
            let tail: Vec<&str> = err.lines().rev().take(12).collect();
            Err(tail.into_iter().rev().collect::<Vec<_>>().join("\n"))
        }
    })
    .await
    .map_err(|e| e.to_string())?
}

// ponytail: rfd off-main-thread is fine on Windows; macOS needs main-thread —
// swap to tauri-plugin-dialog when cross-platform ships.
#[tauri::command]
async fn export_report_md(content: String, suggested_name: String) -> Result<bool, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let Some(path) = rfd::FileDialog::new()
            .set_file_name(&suggested_name)
            .add_filter("Markdown", &["md"])
            .save_file()
        else {
            return Ok(false);
        };
        std::fs::write(&path, content).map_err(|e| e.to_string())?;
        Ok(true)
    })
    .await
    .map_err(|e| e.to_string())?
}

#[tauri::command]
async fn confirm_dialog(title: String, message: String) -> Result<bool, String> {
    tauri::async_runtime::spawn_blocking(move || {
        Ok(rfd::MessageDialog::new()
            .set_title(&title)
            .set_description(&message)
            .set_buttons(rfd::MessageButtons::YesNo)
            .show()
            == rfd::MessageDialogResult::Yes)
    })
    .await
    .map_err(|e| e.to_string())?
}

/// Show the Preferences (Setup) window, building it on first open. It loads the
/// same bundle at `index.html#setup`, which `main.ts` mounts as SetupPage. Closing
/// the window destroys it, so reopening just rebuilds — hence get-or-create here
/// rather than a pre-declared hidden window that can't come back.
fn show_setup_window(app: &tauri::AppHandle) -> Result<(), String> {
    if let Some(win) = app.get_webview_window("setup") {
        win.show().map_err(|e| e.to_string())?;
        win.set_focus().map_err(|e| e.to_string())?;
        return Ok(());
    }
    let win = WebviewWindowBuilder::new(app, "setup", WebviewUrl::App("index.html#setup".into()))
        .title("Preferences")
        .inner_size(720.0, 560.0)
        .build()
        .map_err(|e| e.to_string())?;

    // On first run the main window stays hidden until setup finishes, so closing
    // Preferences here would leave a running process with no window and no way
    // back. Quit instead.
    let handle = app.clone();
    win.on_window_event(move |event| {
        if matches!(event, tauri::WindowEvent::Destroyed) {
            let main_visible = handle
                .get_webview_window("main")
                .and_then(|w| w.is_visible().ok())
                .unwrap_or(false);
            if !main_visible {
                handle.exit(0);
            }
        }
    });
    Ok(())
}

#[tauri::command]
async fn open_setup_window(app: tauri::AppHandle) -> Result<(), String> {
    show_setup_window(&app)
}

/// The main window starts hidden (tauri.conf.json `visible: false`) so an
/// unconfigured launch shows only Preferences, never an empty dashboard.
/// The frontend calls this once it knows which of the two it is.
#[tauri::command]
async fn main_ready(app: tauri::AppHandle, configured: bool) -> Result<(), String> {
    if !configured {
        return show_setup_window(&app);
    }
    show_main(&app)
}

fn show_main(app: &tauri::AppHandle) -> Result<(), String> {
    let win = app
        .get_webview_window("main")
        .ok_or("main window is missing")?;
    win.show().map_err(|e| e.to_string())?;
    win.set_focus().map_err(|e| e.to_string())?;
    Ok(())
}

/// "Done" in the Setup window: reveal the dashboard, then dismiss Preferences.
/// Order matters — showing main first keeps the Destroyed handler above from
/// reading this as "closed before finishing" and quitting the app.
#[tauri::command]
async fn finish_setup(app: tauri::AppHandle) -> Result<(), String> {
    show_main(&app)?;
    // Settings only take effect on restart, and each window has its own JS
    // context (so the main window's config memo is stale). It reloads on this.
    app.emit("setup-done", ()).map_err(|e| e.to_string())?;
    if let Some(win) = app.get_webview_window("setup") {
        win.close().map_err(|e| e.to_string())?;
    }
    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_sql::Builder::default().build())
        .plugin(tauri_plugin_http::init())
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![
            generate_report,
            export_report_md,
            confirm_dialog,
            get_config,
            set_config,
            keygen,
            encryption_key,
            await_oauth_callback,
            run_setup_step,
            pick_history_folder,
            open_setup_window,
            main_ready,
            finish_setup,
            cloud_deploy
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
