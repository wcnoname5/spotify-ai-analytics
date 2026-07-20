use std::path::{Path, PathBuf};
use std::process::Command;

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
            doctor
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
