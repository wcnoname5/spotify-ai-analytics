//! Config storage: a flat JSON file, read and written here and nowhere else.
//!
//! This replaced a `.env` file that was read/written by Python and reached from
//! Rust by spawning `uv run spotify-mcp config get` (~1.7s per read, and
//! impossible in a packaged build, which has no `uv` and no repo checkout).
//!
//! # Where the file lives
//!
//! One rule, no inference:
//!
//! ```text
//! $SPOTIFY_CONFIG set  -> that path
//! otherwise            -> <platform config dir>/config.json
//! ```
//!
//! Development sets `SPOTIFY_CONFIG=./dev.config.json`; a packaged install never
//! has the variable, so it always lands in the platform dir. The two cannot
//! contaminate each other.
//!
//! The predecessor resolved this by reading a `DEV` key out of `Path.cwd()/.env`,
//! so *which config a process used depended on the directory it was launched
//! from* — the "twin .env" class of bug. Nothing here looks at the cwd.
//!
//! # Storage shape
//!
//! A flat `{ "KEY": "value" }` map, deliberately untyped at rest: an older build
//! reading a newer file ignores keys it does not know, and a newer build reading
//! an older file falls back to defaults. Neither errors. `AppConfig` is the
//! typed *view* the frontend gets, derived on read.

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use serde::Serialize;

/// Directory name used by Python's `platformdirs.user_config_dir("spotify-mcp")`.
///
/// The segment really is repeated: platformdirs defaults `appauthor` to
/// `appname` on Windows, giving `%LOCALAPPDATA%\spotify-mcp\spotify-mcp`. It is
/// kept verbatim rather than tidied because the existing `.env` and `history.db`
/// already live there, and `spotify_core/paths.py` still has to agree with this.
const APP_DIRS: [&str; 2] = ["spotify-mcp", "spotify-mcp"];

const CONFIG_FILE: &str = "config.json";

/// Platform config directory, matching `platformdirs.user_config_dir`.
fn platform_config_dir() -> PathBuf {
    #[cfg(windows)]
    let base = std::env::var_os("LOCALAPPDATA").map(PathBuf::from);
    #[cfg(not(windows))]
    let base = std::env::var_os("XDG_CONFIG_HOME")
        .map(PathBuf::from)
        .or_else(|| std::env::var_os("HOME").map(|h| PathBuf::from(h).join(".config")));

    // A machine with neither variable is not a machine we can guess for; the cwd
    // is at least somewhere writable, and doctor will report the odd path.
    base.unwrap_or_else(|| PathBuf::from("."))
        .join(APP_DIRS[0])
        .join(APP_DIRS[1])
}

/// The active config file. See the module docs for the resolution rule.
pub fn config_path() -> PathBuf {
    match std::env::var("SPOTIFY_CONFIG") {
        Ok(raw) if !raw.trim().is_empty() => PathBuf::from(raw.trim()),
        _ => platform_config_dir().join(CONFIG_FILE),
    }
}

/// The data directory (`history.db` lives here), matching `platformdirs.user_data_dir`.
///
/// Derived from the config file's own directory when `SPOTIFY_CONFIG` is set, so
/// a dev config keeps its database next to itself instead of writing into the
/// platform dir the packaged build uses.
pub fn data_dir() -> PathBuf {
    match std::env::var("SPOTIFY_CONFIG") {
        Ok(raw) if !raw.trim().is_empty() => Path::new(raw.trim())
            .parent()
            .map(|p| p.join("data"))
            .unwrap_or_else(|| PathBuf::from("data")),
        _ => platform_config_dir(),
    }
}

type Values = BTreeMap<String, String>;

fn load_values() -> Values {
    let path = config_path();
    let Ok(text) = std::fs::read_to_string(&path) else {
        return Values::new();
    };
    // A corrupt file must not brick the app into an unopenable state: an empty
    // map reads as "nothing configured", which the Setup page already handles.
    serde_json::from_str(&text).unwrap_or_default()
}

fn save_values(values: &Values) -> Result<(), String> {
    let path = config_path();
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|e| format!("{}: {e}", parent.display()))?;
    }
    let text = serde_json::to_string_pretty(values).map_err(|e| e.to_string())?;
    std::fs::write(&path, text + "\n").map_err(|e| format!("{}: {e}", path.display()))
}

fn get(values: &Values, key: &str) -> String {
    // Process env wins, so a shell can override any single key without editing
    // the file — the one precedence rule the .env version had that is worth keeping.
    std::env::var(key)
        .ok()
        .or_else(|| values.get(key).cloned())
        .unwrap_or_default()
        .trim()
        .to_string()
}

/// Which optional settings already have a value. Booleans only, never secrets.
#[derive(Serialize)]
pub struct ConfiguredFlags {
    client_id: bool,
    gemini: bool,
    openai: bool,
    langfuse: bool,
    langsmith: bool,
    worker: bool,
}

#[derive(Serialize)]
pub struct AppConfig {
    /// Kept named `env_file` because the frontend shows it as "where your
    /// settings live" and renaming it is a separate, cosmetic change.
    env_file: String,
    dev: bool,
    history_db_path: String,
    /// Not a secret: PKCE has no client secret, and this value appears in the
    /// authorize URL the user's own browser opens. The frontend needs it to
    /// build that URL.
    spotify_client_id: String,
    /// Which `spotify_tokens` row belongs to this install. Written by the OAuth
    /// step from Spotify's own profile response; "default" until then.
    spotify_user_id: String,
    worker_url: String,
    worker_auth_token: String,
    configured: ConfiguredFlags,
    /// Config-derived readiness checks. The database-derived ones
    /// (`history_has_data`, `tokens_valid`) are composed in `lib/config.ts`,
    /// which already holds an open SQLite handle.
    checks: BTreeMap<String, bool>,
}

/// Resolve `history.db`: an explicit `HISTORY_DB_PATH` wins, relative values
/// resolve against the data dir (not the cwd, so the result does not depend on
/// where the app was launched from), and absent means the default location.
///
/// This precedence is the only reason the old `config get` subcommand existed
/// (`spotify_core/config.py`'s `resolve_path`). It lives here now.
fn history_db_path(values: &Values) -> PathBuf {
    let raw = get(values, "HISTORY_DB_PATH");
    if raw.is_empty() {
        return data_dir().join("history.db");
    }
    let path = PathBuf::from(&raw);
    if path.is_absolute() {
        path
    } else {
        data_dir().join(path)
    }
}

pub fn read() -> AppConfig {
    let values = load_values();

    let spotify_client_id = get(&values, "SPOTIFY_CLIENT_ID");
    let client_id = !spotify_client_id.is_empty();
    let fernet_key = !get(&values, "TOKEN_ENCRYPT_KEY").is_empty();
    let worker_url = get(&values, "WORKER_URL");
    let worker_auth_token = get(&values, "WORKER_AUTH_TOKEN");

    let mut checks = BTreeMap::new();
    checks.insert("client_id".to_string(), client_id);
    checks.insert("fernet_key".to_string(), fernet_key);

    AppConfig {
        env_file: config_path().display().to_string(),
        // `dev` now means exactly "running against a non-default config file".
        dev: std::env::var("SPOTIFY_CONFIG").is_ok_and(|v| !v.trim().is_empty()),
        history_db_path: history_db_path(&values).display().to_string(),
        spotify_client_id,
        spotify_user_id: {
            let id = get(&values, "SPOTIFY_USER_ID");
            if id.is_empty() { "default".to_string() } else { id }
        },
        configured: ConfiguredFlags {
            client_id,
            gemini: !get(&values, "GEMINI_API_KEY").is_empty(),
            openai: !get(&values, "OPENAI_API_KEY").is_empty(),
            langfuse: !get(&values, "LANGFUSE_PUBLIC_KEY").is_empty()
                && !get(&values, "LANGFUSE_SECRET_KEY").is_empty()
                && !get(&values, "LANGFUSE_BASE_URL").is_empty(),
            langsmith: !get(&values, "LANGSMITH_API_KEY").is_empty(),
            worker: !worker_url.is_empty() && !worker_auth_token.is_empty(),
        },
        worker_url,
        worker_auth_token,
        checks,
    }
}

/// The raw `TOKEN_ENCRYPT_KEY`, or None when unset.
///
/// The only getter that returns a secret. It exists because the frontend does
/// the Fernet encryption, using the same `fernet.ts` the Worker cron decrypts
/// with — see the `encryption_key` command for why that is the tradeoff taken.
pub fn fernet_key_value() -> Option<String> {
    let key = get(&load_values(), "TOKEN_ENCRYPT_KEY");
    if key.is_empty() {
        None
    } else {
        Some(key)
    }
}

/// Upsert `KEY=VALUE` pairs, leaving every other key (including ones this build
/// does not know about) untouched.
pub fn write(pairs: &[String]) -> Result<String, String> {
    let mut values = load_values();
    for pair in pairs {
        let Some((key, value)) = pair.split_once('=') else {
            return Err(format!("expected KEY=VALUE, got {pair:?}"));
        };
        let key = key.trim();
        if key.is_empty() {
            return Err(format!("expected KEY=VALUE, got {pair:?}"));
        }
        values.insert(key.to_string(), value.trim().to_string());
    }
    save_values(&values)?;
    Ok(config_path().display().to_string())
}

/// Generate `TOKEN_ENCRYPT_KEY` if absent. Returns whether one was created.
///
/// Never overwrites: regenerating orphans every token already encrypted with the
/// old key, and the user has no way to get those back.
pub fn ensure_fernet_key() -> Result<bool, String> {
    let mut values = load_values();
    if !get(&values, "TOKEN_ENCRYPT_KEY").is_empty() {
        return Ok(false);
    }
    values.insert("TOKEN_ENCRYPT_KEY".to_string(), fernet_key()?);
    save_values(&values)?;
    Ok(true)
}

/// A Fernet key: 32 random bytes, base64url with padding — the format
/// `cryptography.fernet.Fernet.generate_key()` produces and `worker/src/fernet.ts`
/// expects (first 16 bytes sign, last 16 encrypt).
fn fernet_key() -> Result<String, String> {
    let mut bytes = [0u8; 32];
    getrandom::fill(&mut bytes).map_err(|e| format!("no OS randomness available: {e}"))?;
    Ok(base64url_pad(&bytes))
}

fn base64url_pad(bytes: &[u8]) -> String {
    const ALPHABET: &[u8; 64] =
        b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
    let mut out = String::with_capacity((bytes.len() + 2) / 3 * 4);
    for chunk in bytes.chunks(3) {
        let b = [chunk[0], *chunk.get(1).unwrap_or(&0), *chunk.get(2).unwrap_or(&0)];
        let n = u32::from(b[0]) << 16 | u32::from(b[1]) << 8 | u32::from(b[2]);
        for i in 0..4 {
            if i <= chunk.len() {
                out.push(ALPHABET[(n >> (18 - i * 6) & 0x3F) as usize] as char);
            } else {
                out.push('=');
            }
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::{Mutex, MutexGuard};

    // SPOTIFY_CONFIG is process-global, so these tests cannot run concurrently.
    static ENV_LOCK: Mutex<()> = Mutex::new(());

    struct Env(#[allow(dead_code)] MutexGuard<'static, ()>);

    impl Env {
        fn with(path: Option<&Path>) -> Self {
            let guard = ENV_LOCK.lock().unwrap_or_else(|e| e.into_inner());
            match path {
                Some(p) => std::env::set_var("SPOTIFY_CONFIG", p),
                None => std::env::remove_var("SPOTIFY_CONFIG"),
            }
            Env(guard)
        }
    }

    impl Drop for Env {
        fn drop(&mut self) {
            std::env::remove_var("SPOTIFY_CONFIG");
        }
    }

    fn tmpdir() -> PathBuf {
        let dir = std::env::temp_dir().join(format!("spotify-cfg-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }

    #[test]
    fn spotify_config_overrides_the_platform_dir() {
        let dir = tmpdir();
        let target = dir.join("dev.config.json");
        let _env = Env::with(Some(&target));
        assert_eq!(config_path(), target);
        // The whole point of the override: prod and dev must not share a file.
        assert_ne!(config_path(), platform_config_dir().join(CONFIG_FILE));
    }

    #[test]
    fn without_the_variable_it_is_the_platform_dir() {
        let _env = Env::with(None);
        assert_eq!(config_path(), platform_config_dir().join(CONFIG_FILE));
        assert!(config_path().ends_with(Path::new("spotify-mcp/config.json")));
    }

    #[test]
    fn a_dev_config_keeps_its_data_beside_itself() {
        let dir = tmpdir();
        let _env = Env::with(Some(&dir.join("dev.config.json")));
        assert_eq!(data_dir(), dir.join("data"));
    }

    #[test]
    fn round_trips_and_preserves_unknown_keys() {
        let dir = tmpdir();
        let target = dir.join("roundtrip.config.json");
        let _ = std::fs::remove_file(&target);
        let _env = Env::with(Some(&target));

        // A key no build knows about — stands in for one written by a newer version.
        write(&["FROM_THE_FUTURE=keep me".into()]).unwrap();
        write(&["SPOTIFY_CLIENT_ID=abc".into(), "WORKER_URL=https://w.dev".into()]).unwrap();

        let values = load_values();
        assert_eq!(values.get("FROM_THE_FUTURE").unwrap(), "keep me");
        assert_eq!(read().worker_url, "https://w.dev");
        assert!(read().configured.client_id);
    }

    #[test]
    fn missing_file_reads_as_unconfigured_rather_than_failing() {
        let dir = tmpdir();
        let _env = Env::with(Some(&dir.join("does-not-exist.json")));
        let cfg = read();
        assert!(!cfg.configured.client_id);
        assert!(!cfg.configured.worker);
        assert_eq!(cfg.worker_url, "");
    }

    #[test]
    fn corrupt_file_reads_as_unconfigured_rather_than_failing() {
        let dir = tmpdir();
        let target = dir.join("corrupt.config.json");
        std::fs::write(&target, "{ this is not json").unwrap();
        let _env = Env::with(Some(&target));
        assert!(!read().configured.client_id);
    }

    #[test]
    fn relative_history_db_resolves_against_the_data_dir_not_the_cwd() {
        let dir = tmpdir();
        let target = dir.join("relpath.config.json");
        let _ = std::fs::remove_file(&target);
        let _env = Env::with(Some(&target));
        write(&["HISTORY_DB_PATH=custom.db".into()]).unwrap();
        assert_eq!(
            PathBuf::from(read().history_db_path),
            dir.join("data").join("custom.db")
        );
    }

    #[test]
    fn ensure_fernet_key_is_idempotent_and_never_rotates() {
        let dir = tmpdir();
        let target = dir.join("fernet.config.json");
        let _ = std::fs::remove_file(&target);
        let _env = Env::with(Some(&target));

        assert!(ensure_fernet_key().unwrap(), "first call creates a key");
        let first = load_values().get("TOKEN_ENCRYPT_KEY").unwrap().clone();
        assert!(!ensure_fernet_key().unwrap(), "second call is a no-op");
        assert_eq!(load_values().get("TOKEN_ENCRYPT_KEY").unwrap(), &first);
    }

    #[test]
    fn fernet_key_is_32_bytes_base64url() {
        let key = fernet_key().unwrap();
        // 32 bytes -> 44 base64 chars including one '=' of padding.
        assert_eq!(key.len(), 44);
        assert!(key.ends_with('='));
        assert!(key[..43].bytes().all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_'));
    }

    #[test]
    fn write_rejects_a_pair_without_an_equals_sign() {
        let dir = tmpdir();
        let _env = Env::with(Some(&dir.join("bad.config.json")));
        assert!(write(&["NOEQUALS".into()]).is_err());
        assert!(write(&["=novalue".into()]).is_err());
    }
}
