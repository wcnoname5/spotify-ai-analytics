mod cloudflare;
mod config;
mod oauth;

use std::path::PathBuf;
use std::process::Command;
use tauri::{Emitter, Manager, WebviewUrl, WebviewWindowBuilder};

// ponytail: the last spawn in the app, and dev-only. The report is out of scope
// for the first release (`ReportPage` is hidden unless the app is running against
// a dev config). It goes when the report backend is settled — a PyInstaller
// sidecar or LangGraph.js — and `repo_root()` goes with it.
//
// `run_setup_step` and its `spotify-mcp` runner used to be here too. Every step
// it dispatched (oauth, import, sync) is now in the app or on the Worker, so the
// list shrank to nothing rather than being replaced.
const REPORT_CMD: &[&str] = &["uv", "run", "python", "-m", "spotify_core.report"];

/// Repo root, resolved at *compile* time — so anything using this only works on
/// the machine that built it. Reachable only from `generate_report` below, which
/// is hidden outside a dev config; never from a path a packaged user can take.
fn repo_root() -> PathBuf {
    std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../..")
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

/// Stand up the user's Cloudflare backend, streaming progress to the Setup page.
///
/// Calls Cloudflare's REST API directly (see cloudflare.rs). It used to spawn
/// `spotify-mcp cloud deploy`, which drove `npx wrangler` — fine from a checkout,
/// impossible for the external users this step exists for, who have neither
/// Python nor Node.
///
/// Progress goes out as `cloud-log` events rather than a return value: the deploy
/// takes minutes and a button frozen that long reads as a hang.
///
/// `api_token` is used and dropped; it is never written to the config file.
#[tauri::command]
async fn cloud_deploy(
    app: tauri::AppHandle,
    name: String,
    api_token: String,
    rotate: bool,
) -> Result<(), String> {
    tauri::async_runtime::spawn_blocking(move || {
        if api_token.trim().is_empty() {
            return Err("Paste a Cloudflare API token first.".to_string());
        }
        let cfg = config::deploy_inputs();
        if cfg.client_id.is_empty() || cfg.fernet_key.is_empty() {
            return Err(
                "Finish the Spotify Client ID step first — the Worker needs it as a secret."
                    .to_string(),
            );
        }

        let log = move |line: String| {
            let _ = app.emit("cloud-log", line);
        };

        let result = cloudflare::deploy(
            api_token,
            name.trim(),
            &cfg.client_id,
            &cfg.fernet_key,
            // Reusing the existing token unless asked to rotate: a new one on
            // every deploy silently 401s every other machine pointing here.
            if rotate { None } else { Some(cfg.worker_auth_token) },
            &log,
        )?;

        config::write(&[
            format!("WORKER_URL={}", result.worker_url),
            format!("WORKER_AUTH_TOKEN={}", result.auth_token),
        ])?;
        log(format!("Saved WORKER_URL to {}", config::config_path().display()));
        Ok(())
    })
    .await
    .map_err(|e| e.to_string())?
}

/// The `Streaming_History_Audio_*.json` files in a chosen export folder, sorted.
///
/// Paths only. A full export can be hundreds of MB, so the frontend reads and
/// posts one file at a time rather than receiving the lot over IPC at once.
#[tauri::command]
fn list_history_files(folder: String) -> Result<Vec<String>, String> {
    let dir = std::path::Path::new(&folder);
    let entries = std::fs::read_dir(dir).map_err(|e| format!("{folder}: {e}"))?;

    let mut files: Vec<String> = entries
        .filter_map(Result::ok)
        .map(|e| e.path())
        .filter(|p| {
            let name = p.file_name().and_then(|n| n.to_str()).unwrap_or("");
            // Spotify's own naming. Matching *.json instead would pick up the
            // export's Userdata.json and Follow.json, which are not plays.
            name.starts_with("Streaming_History_Audio_") && name.ends_with(".json")
        })
        .map(|p| p.display().to_string())
        .collect();
    // Chronological by name, so a partial import covers a contiguous period.
    files.sort();

    if files.is_empty() {
        return Err(format!(
            "no Streaming_History_Audio_*.json files in {folder}. \
             Pick the folder from Spotify's extended streaming history export."
        ));
    }
    Ok(files)
}

/// One export file's contents.
///
/// Restricted to the export's own filenames so this cannot be turned into a
/// read-any-file command from the webview.
#[tauri::command]
fn read_history_file(path: String) -> Result<String, String> {
    let p = std::path::Path::new(&path);
    let name = p.file_name().and_then(|n| n.to_str()).unwrap_or("");
    if !(name.starts_with("Streaming_History_Audio_") && name.ends_with(".json")) {
        return Err(format!("refusing to read {name}: not an export history file"));
    }
    std::fs::read_to_string(p).map_err(|e| format!("{path}: {e}"))
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
            list_history_files,
            read_history_file,
            pick_history_folder,
            open_setup_window,
            main_ready,
            finish_setup,
            cloud_deploy
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
