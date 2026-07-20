use std::path::Path;
use std::process::Command;

// ponytail: dev-only runner; a packaged PyInstaller sidecar swaps this vector + cwd.
const REPORT_CMD: &[&str] = &["uv", "run", "python", "-m", "spotify_core.report"];

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
        let repo_root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../..");
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
        .invoke_handler(tauri::generate_handler![generate_report, export_report_md, confirm_dialog])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
