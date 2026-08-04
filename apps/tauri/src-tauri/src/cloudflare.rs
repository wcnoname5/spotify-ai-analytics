//! Standing up the user's own Cloudflare backend, over the REST API.
//!
//! This replaced `spotify-mcp cloud deploy`, which drove `npx wrangler`. 
//! Since for user they don't need to install Node or pyhton 
//!
//! The Worker script is bundled at compile time (see build.rs) and embedded, so
//! the only thing that leaves this machine is HTTPS to api.cloudflare.com.
//!
//! Nothing here prints a token: the output is streamed into the Setup page's log
//! pane and this repo is public.

use std::time::Duration;

use serde::Deserialize;

/// The bundled Worker, produced by build.rs. A missing bundle is a compile error.
const WORKER_JS: &str = include_str!(env!("WORKER_BUNDLE"));

const API: &str = "https://api.cloudflare.com/client/v4";

/// Matches `compatibility_date` in wrangler.toml.example. Pinned rather than
/// "today": a moving date silently changes Workers runtime semantics between one
/// user's deploy and the next.
const COMPATIBILITY_DATE: &str = "2025-01-09";

/// :07 keeps clear of the top-of-hour congestion window. Same value as
/// wrangler.toml.example's `crons`.
const CRON: &str = "7 * * * *";

/// A freshly-set secret takes a few seconds to reach every edge node, so the
/// first authenticated call after a deploy can 401. Real propagation delay, not a
/// flaky-test band-aid.
const PROPAGATION_ATTEMPTS: u32 = 5;
const PROPAGATION_BACKOFF: Duration = Duration::from_secs(5);

/// Cloudflare wraps every response in the same envelope.
#[derive(Deserialize)]
struct Envelope<T> {
    success: bool,
    #[serde(default)]
    errors: Vec<ApiError>,
    result: Option<T>,
}

#[derive(Deserialize)]
struct ApiError {
    code: i64,
    message: String,
}

impl std::fmt::Display for ApiError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{} (code {})", self.message, self.code)
    }
}

#[derive(Deserialize)]
struct Account {
    id: String,
    name: String,
}

#[derive(Deserialize)]
struct D1Database {
    uuid: String,
}

#[derive(Deserialize)]
struct Subdomain {
    subdomain: String,
}

/// Cloudflare error code for "a D1 database with that name already exists".
/// Reusing it is the intended behaviour — deploying twice must not be an error.
const D1_ALREADY_EXISTS: i64 = 7502;

/// Progress goes to the caller as it happens; the deploy takes minutes and a
/// button frozen for that long reads as a hang.
pub type Log<'a> = &'a (dyn Fn(String) + Send + Sync);

pub struct Deployer {
    client: reqwest::blocking::Client,
    token: String,
}

impl Deployer {
    pub fn new(api_token: String) -> Result<Self, String> {
        let client = reqwest::blocking::Client::builder()
            // Uploading the script and applying migrations are the slow calls;
            // no request here legitimately takes minutes.
            .timeout(Duration::from_secs(120))
            .build()
            .map_err(|e| format!("could not start an HTTPS client: {e}"))?;
        Ok(Self { client, token: api_token })
    }

    fn request(&self, method: reqwest::Method, path: &str) -> reqwest::blocking::RequestBuilder {
        self.client
            .request(method, format!("{API}{path}"))
            .bearer_auth(&self.token)
    }

    /// Send a request and unwrap Cloudflare's envelope.
    ///
    /// `tolerate` lets a caller accept a specific error code as success — the one
    /// case being "database already exists", which is what a second deploy hits.
    fn send<T: serde::de::DeserializeOwned>(
        &self,
        req: reqwest::blocking::RequestBuilder,
        what: &str,
        tolerate: &[i64],
    ) -> Result<Option<T>, String> {
        let resp = req.send().map_err(|e| format!("{what}: {e}"))?;
        let status = resp.status();
        let body = resp.text().map_err(|e| format!("{what}: {e}"))?;

        let envelope: Envelope<T> = serde_json::from_str(&body).map_err(|_| {
            // A non-JSON body here is usually an HTML error page from a proxy;
            // showing the raw text is more useful than a parse error.
            format!("{what}: HTTP {status}, unexpected response: {}", body.chars().take(300).collect::<String>())
        })?;

        if envelope.success {
            return Ok(envelope.result);
        }
        if envelope.errors.iter().any(|e| tolerate.contains(&e.code)) {
            return Ok(None);
        }
        let detail = envelope
            .errors
            .iter()
            .map(ToString::to_string)
            .collect::<Vec<_>>()
            .join("; ");
        Err(format!("{what}: {}", if detail.is_empty() { format!("HTTP {status}") } else { detail }))
    }

    /// The account this API token belongs to.
    ///
    /// The account ID is derived from the API token rather than passed in.
    fn account(&self) -> Result<Account, String> {
        let accounts: Vec<Account> = self
            .send(self.request(reqwest::Method::GET, "/accounts"), "reading your Cloudflare account", &[])?
            .unwrap_or_default();

        match accounts.len() {
            0 => Err("that API token has no account access: check its permissions".to_string()),
            1 => Ok(accounts.into_iter().next().expect("len checked")),
            _ => {
                // Multiple accounts means we would be guessing which one to deploy to.
                // Instead of guessing we just throws an error
                let names: Vec<&str> = accounts.iter().map(|a| a.name.as_str()).collect();
                Err(format!(
                    "that API token covers {} accounts ({}). Create a token scoped to just one.",
                    accounts.len(),
                    names.join(", ")
                ))
            }
        }
    }

    fn database_id(&self, account: &str, name: &str) -> Result<String, String> {
        let created: Option<D1Database> = self.send(
            self.request(reqwest::Method::POST, &format!("/accounts/{account}/d1/database"))
                .json(&serde_json::json!({ "name": name })),
            "creating the D1 database",
            &[D1_ALREADY_EXISTS],
        )?;
        if let Some(db) = created {
            return Ok(db.uuid);
        }

        // Already existed: look it up so a re-deploy targets the same database
        // rather than failing.
        #[derive(Deserialize)]
        struct Listed {
            uuid: String,
            name: String,
        }
        let listed: Vec<Listed> = self
            .send(
                self.request(reqwest::Method::GET, &format!("/accounts/{account}/d1/database"))
                    .query(&[("name", name)]),
                "looking up the existing D1 database",
                &[],
            )?
            .unwrap_or_default();
        listed
            .into_iter()
            .find(|db| db.name == name)
            .map(|db| db.uuid)
            .ok_or_else(|| format!("D1 database {name:?} exists but could not be read back — check the token's D1 permissions"))
    }

    /// Apply the migrations, in filename order.
    ///
    /// Every statement is `CREATE TABLE/INDEX IF NOT EXISTS`, so re-running the
    /// whole set is a no-op. That is why there is no migration bookkeeping table
    /// here: wrangler kept one, and reproducing it would be state to keep correct
    /// for no behaviour difference. It stops being true the moment a migration
    /// contains an ALTER — see the local migration runner, which does track a
    /// version, and mirror that here when it happens.
    fn migrate(&self, account: &str, db: &str, log: Log) -> Result<(), String> {
        for (name, sql) in MIGRATIONS {
            log(format!("    {name}"));
            self.send::<serde_json::Value>(
                self.request(
                    reqwest::Method::POST,
                    &format!("/accounts/{account}/d1/database/{db}/query"),
                )
                .json(&serde_json::json!({ "sql": sql })),
                &format!("applying {name}"),
                &[],
            )?;
        }
        Ok(())
    }

    /// Upload the Worker with its D1 binding and secrets in one call.
    ///
    /// Secrets ride along as `secret_text` bindings rather than going through the
    /// separate secrets endpoint: one request instead of four, and the script is
    /// never live for a moment without the values it needs.
    fn upload(
        &self,
        account: &str,
        worker: &str,
        db_id: &str,
        auth_token: &str,
        client_id: &str,
        fernet_key: &str,
    ) -> Result<(), String> {
        let metadata = serde_json::json!({
            "main_module": "worker.js",
            "compatibility_date": COMPATIBILITY_DATE,
            "bindings": [
                { "type": "d1", "name": "DB", "id": db_id },
                { "type": "secret_text", "name": "AUTH_TOKEN", "text": auth_token },
                { "type": "secret_text", "name": "SPOTIFY_CLIENT_ID", "text": client_id },
                { "type": "secret_text", "name": "TOKEN_ENCRYPT_KEY", "text": fernet_key },
            ],
            "observability": { "enabled": true },
        });

        let form = reqwest::blocking::multipart::Form::new()
            .text("metadata", metadata.to_string())
            .part(
                "worker.js",
                reqwest::blocking::multipart::Part::text(WORKER_JS)
                    .file_name("worker.js")
                    .mime_str("application/javascript+module")
                    .map_err(|e| e.to_string())?,
            );

        self.send::<serde_json::Value>(
            self.request(
                reqwest::Method::PUT,
                &format!("/accounts/{account}/workers/scripts/{worker}"),
            )
            .multipart(form),
            "uploading the Worker",
            &[],
        )?;
        Ok(())
    }

    /// The hourly cron. Separate call: schedules are not part of script upload.
    fn set_cron(&self, account: &str, worker: &str) -> Result<(), String> {
        self.send::<serde_json::Value>(
            self.request(
                reqwest::Method::PUT,
                &format!("/accounts/{account}/workers/scripts/{worker}/schedules"),
            )
            .json(&serde_json::json!([{ "cron": CRON }])),
            "setting the hourly schedule",
            &[],
        )?;
        Ok(())
    }

    /// Enable workers.dev for the script and return its public URL.
    fn enable_subdomain(&self, account: &str, worker: &str) -> Result<String, String> {
        // The account's workers.dev subdomain. Absent means the user has never
        // enabled one, which they must do once in the dashboard.
        let sub: Subdomain = self
            .send(
                self.request(reqwest::Method::GET, &format!("/accounts/{account}/workers/subdomain")),
                "reading your workers.dev subdomain",
                &[],
            )?
            .ok_or(
                "your account has no workers.dev subdomain yet. Create one in the \
                 Cloudflare dashboard under Workers & Pages, then press Deploy again.",
            )?;

        self.send::<serde_json::Value>(
            self.request(
                reqwest::Method::POST,
                &format!("/accounts/{account}/workers/scripts/{worker}/subdomain"),
            )
            .json(&serde_json::json!({ "enabled": true })),
            "enabling the Worker's public URL",
            &[],
        )?;

        Ok(format!("https://{worker}.{}.workers.dev", sub.subdomain))
    }

    /// Poll the deployed Worker until its AUTH_TOKEN secret has propagated.
    ///
    /// Without this the app reports success and the first sync 401s, which reads
    /// as "the token is wrong" rather than "wait five seconds".
    fn await_ready(&self, url: &str, auth_token: &str, log: Log) -> Result<(), String> {
        for attempt in 1..=PROPAGATION_ATTEMPTS {
            let resp = self
                .client
                .get(format!("{url}/api/tracks/count"))
                .bearer_auth(auth_token)
                .send();
            match resp {
                Ok(r) if r.status().is_success() => return Ok(()),
                _ if attempt < PROPAGATION_ATTEMPTS => {
                    log(format!(
                        "    (not answering yet — attempt {attempt}/{PROPAGATION_ATTEMPTS}, \
                         retrying in {}s)",
                        PROPAGATION_BACKOFF.as_secs()
                    ));
                    std::thread::sleep(PROPAGATION_BACKOFF);
                }
                _ => {
                    return Err(
                        "the Worker is deployed but not answering yet. Give it a minute, \
                         then reopen the app."
                            .to_string(),
                    )
                }
            }
        }
        Ok(())
    }
}

/// The migrations, embedded in filename order.
///
/// Listed explicitly rather than globbed: `include_str!` needs literal paths, and
/// an explicit list means adding a migration without wiring it up is a visible
/// omission rather than a silent one.
const MIGRATIONS: &[(&str, &str)] = &[
    (
        "0001_init.sql",
        include_str!("../../../../packages/core/spotify_core/db/sql/migrations/0001_init.sql"),
    ),
    (
        "0002_reports.sql",
        include_str!("../../../../packages/core/spotify_core/db/sql/migrations/0002_reports.sql"),
    ),
];

pub struct DeployResult {
    pub worker_url: String,
    pub auth_token: String,
}

/// Create D1, migrate, upload the Worker, set the cron, and wait for it to answer.
///
/// `existing_token` is reused when present. Minting a new one on every deploy
/// silently 401s every other machine pointing at this Worker, so rotation has to
/// be something the user asks for.
#[allow(clippy::too_many_arguments)]
pub fn deploy(
    api_token: String,
    name: &str,
    client_id: &str,
    fernet_key: &str,
    existing_token: Option<String>,
    log: Log,
) -> Result<DeployResult, String> {
    let cf = Deployer::new(api_token)?;
    let worker = format!("{name}-worker");

    let auth_token = match existing_token {
        Some(t) if !t.is_empty() => t,
        _ => {
            log("Generated a new Worker auth token.".into());
            new_auth_token()?
        }
    };

    log("==> [1/6] Checking your Cloudflare account".into());
    let account = cf.account()?;
    log(format!("    {}", account.name));

    log(format!("==> [2/6] D1 database: {name}"));
    let db_id = cf.database_id(&account.id, name)?;

    log("==> [3/6] Applying migrations".into());
    cf.migrate(&account.id, &db_id, log)?;

    log("==> [4/6] Uploading the Worker (secrets are never printed)".into());
    cf.upload(&account.id, &worker, &db_id, &auth_token, client_id, fernet_key)?;

    log("==> [5/6] Scheduling the hourly sync".into());
    cf.set_cron(&account.id, &worker)?;

    log("==> [6/6] Enabling the public URL".into());
    let worker_url = cf.enable_subdomain(&account.id, &worker)?;
    cf.await_ready(&worker_url, &auth_token, log)?;

    log(format!("Done: D1 {name:?}, Worker live, hourly cron at :07."));
    Ok(DeployResult { worker_url, auth_token })
}

/// 32 random bytes as hex — the Worker compares it as an opaque string.
fn new_auth_token() -> Result<String, String> {
    let mut bytes = [0u8; 32];
    getrandom::fill(&mut bytes).map_err(|e| format!("no OS randomness available: {e}"))?;
    Ok(bytes.iter().map(|b| format!("{b:02x}")).collect())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_bundled_worker_is_a_real_module() {
        // Guards the build.rs wiring: a broken bundle would otherwise only show
        // up when a user pressed Deploy.
        assert!(WORKER_JS.len() > 1000, "bundle looks empty: {} bytes", WORKER_JS.len());
        assert!(WORKER_JS.contains("scheduled"), "no cron handler in the bundle");
        assert!(WORKER_JS.contains("/api/tracks"), "no routes in the bundle");
        // esbuild --format=esm must leave a default export for main_module.
        assert!(WORKER_JS.contains("export"), "not an ES module");
    }

    #[test]
    fn migrations_are_embedded_in_order() {
        assert_eq!(MIGRATIONS[0].0, "0001_init.sql");
        assert!(MIGRATIONS[0].1.contains("listening_history"));
        assert!(MIGRATIONS[1].1.contains("reports"));
    }

    #[test]
    fn the_cron_matches_the_wrangler_config() {
        // Two places declare the schedule; a checkout deploy and an app deploy
        // producing different crons would be invisible until a sync went missing.
        let toml = include_str!("../../../../worker/wrangler.toml.example");
        assert!(toml.contains(CRON), "wrangler.toml.example no longer uses {CRON}");
        assert!(toml.contains(COMPATIBILITY_DATE), "compatibility_date drifted");
    }

    #[test]
    fn auth_tokens_are_64_hex_chars_and_do_not_repeat() {
        let a = new_auth_token().unwrap();
        assert_eq!(a.len(), 64);
        assert!(a.bytes().all(|b| b.is_ascii_hexdigit()));
        assert_ne!(a, new_auth_token().unwrap());
    }
}
