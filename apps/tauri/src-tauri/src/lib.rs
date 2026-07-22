use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use tauri::{Emitter, Manager, WebviewUrl, WebviewWindowBuilder};

// ponytail: dev-only runner; a packaged PyInstaller sidecar swaps this vector + cwd.
const REPORT_CMD: &[&str] = &["uv", "run", "python", "-m", "spotify_core.report"];
// The single CLI entry point every setup step goes through, so packaging bundles one exe.
const CLI_CMD: &[&str] = &["uv", "run", "spotify-mcp"];

fn repo_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../..")
}

/// Run a `spotify-mcp` subcommand from the repo root and return its stdout.
///
/// cwd matters: `paths.is_dev()` reads the *cwd* .env, so running from anywhere
/// else would silently resolve a different config dir than the CLI does.
///
/// `accept_failure` is for `doctor`, which exits 1 whenever the environment is
/// not ready — the normal state mid-setup. Treating that as a spawn error would
/// make every incomplete setup look like a crash.
fn run_cli(args: &[String], accept_failure: bool) -> Result<String, String> {
    let out = Command::new(CLI_CMD[0])
        .args(&CLI_CMD[1..])
        .args(args)
        .current_dir(repo_root())
        .env("PYTHONUTF8", "1")
        .output()
        .map_err(|e| format!("failed to spawn `{}`: {e}", CLI_CMD[0]))?;
    if out.status.success() || accept_failure {
        Ok(String::from_utf8_lossy(&out.stdout).into_owned())
    } else {
        let err = String::from_utf8_lossy(&out.stderr);
        let tail: Vec<&str> = err.lines().rev().take(12).collect();
        Err(tail.into_iter().rev().collect::<Vec<_>>().join("\n"))
    }
}

/// Effective runtime config as a JSON string; the frontend parses it.
/// Replaces the old build-time Vite `define` constants.
#[tauri::command]
async fn get_config() -> Result<String, String> {
    tauri::async_runtime::spawn_blocking(|| {
        run_cli(&["config".into(), "get".into()], false)
    })
    .await
    .map_err(|e| e.to_string())?
}

/// Upsert `KEY=VALUE` pairs into the resolved .env. Writes go through Python
/// (`env_file.upsert`) so the merge logic exists in exactly one place.
/// Callers must tell the user changes apply on restart.
#[tauri::command]
async fn set_config(pairs: Vec<String>) -> Result<String, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let mut args = vec!["config".to_string(), "set".to_string()];
        args.extend(pairs);
        run_cli(&args, false)
    })
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
            "keygen" => vec!["config".into(), "keygen".into()],
            // Fallback for users whose Spotify export has not arrived yet:
            // pulls the last ~50 plays so the dashboard is not empty.
            "sync" => vec!["sync".into()],
            "import" => vec![
                "import-history".into(),
                "--from".into(),
                arg.ok_or("import step requires a path")?,
            ],
            other => return Err(format!("unknown setup step: {other}")),
        };
        run_cli(&args, false)
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

/// Environment readiness report as a JSON string. Exit code deliberately ignored.
#[tauri::command]
async fn doctor() -> Result<String, String> {
    tauri::async_runtime::spawn_blocking(|| {
        run_cli(&["doctor".into(), "--json".into()], true)
    })
    .await
    .map_err(|e| e.to_string())?
}

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
            doctor,
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
