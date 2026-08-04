use std::path::{Path, PathBuf};
use std::process::Command;

fn repo_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../..")
}

/// Bundle the Worker into one ES module for `cloudflare.rs` to `include_str!`.
///
/// Here rather than in `beforeBuildCommand` so a plain `cargo build` also
/// produces it: a broken Worker becomes a compile error, not a failed Deploy on
/// a user's machine. Node is needed to *build* (Vite already required it), not for run
fn bundle_worker() {
    let worker = repo_root().join("worker");
    let outfile = PathBuf::from(std::env::var("OUT_DIR").expect("cargo sets OUT_DIR")).join("worker.js");

    // Without these, cargo caches the bundle and a deploy ships stale code.
    println!("cargo:rerun-if-changed={}", worker.join("src").display());
    println!("cargo:rerun-if-changed={}", repo_root().join("packages/shared-ts").display());

    // On Windows npx is `npx.cmd`; CreateProcess only looks for `.exe`.
    let candidates: &[&str] = if cfg!(windows) { &["npx.cmd", "npx"] } else { &["npx"] };

    let mut last_err = None;
    for exe in candidates {
        let result = Command::new(exe)
            .args(["--no-install", "esbuild", "src/index.ts", "--bundle", "--format=esm", "--target=es2022"])
            .arg(format!("--outfile={}", outfile.display()))
            .current_dir(&worker)
            .output();

        match result {
            Ok(out) if out.status.success() => {
                println!("cargo:rustc-env=WORKER_BUNDLE={}", outfile.display());
                return;
            }
            // esbuild ran and rejected the source; another `npx` won't help.
            Ok(out) => {
                last_err = Some(String::from_utf8_lossy(&out.stderr).into_owned());
                break;
            }
            Err(e) => last_err = Some(e.to_string()),
        }
    }

    panic!(
        "could not bundle the Worker. Run `npm install` in worker/ first.\n{}",
        last_err.unwrap_or_default()
    );
}

fn main() {
    bundle_worker();
    tauri_build::build()
}
