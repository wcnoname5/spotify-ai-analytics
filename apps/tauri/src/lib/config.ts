// Runtime config, read from the Rust side (src-tauri/src/config.rs), which owns
// the config file and its path resolution.
//
// Changes written by setConfig apply on restart: rebuilding the DB handle and
// sync client mid-session is not worth it for a value edited a few times ever.
import { invoke } from "@tauri-apps/api/core";

// Checked inline rather than imported from db.ts: db.ts imports this module,
// and the cycle would be resolved at module-init time.
const inTauri = () => "__TAURI_INTERNALS__" in window;

/** Which optional settings already have a value. Booleans only, never secrets. */
export interface ConfiguredFlags {
  /** Setup has been started at all — the main window's gate. */
  client_id: boolean;
  gemini: boolean;
  openai: boolean;
  langfuse: boolean;
  worker: boolean;
}

export interface AppConfig {
  env_file: string;
  dev: boolean;
  history_db_path: string;
  /** Not a secret — PKCE has no client secret and this appears in the authorize URL. */
  spotify_client_id: string;
  /** Which `spotify_tokens` row belongs to this install. "default" until OAuth runs. */
  spotify_user_id: string;
  worker_url: string;
  worker_auth_token: string;
  /** Stack name the deploy used; empty on installs deployed before it was recorded. */
  worker_name: string;
  configured: ConfiguredFlags;
  /** Config-derived readiness checks. DB-derived ones are added by runDoctor. */
  checks: Record<string, boolean>;
}

const BROWSER_FALLBACK: AppConfig = {
  env_file: "",
  dev: false,
  history_db_path: "",
  spotify_client_id: "",
  spotify_user_id: "default",
  worker_url: "",
  worker_auth_token: "",
  worker_name: "",
  configured: {
    client_id: false, gemini: false, openai: false, langfuse: false, worker: false,
  },
  checks: {},
};

let configPromise: Promise<AppConfig> | null = null;

/** Memoized runtime config. One read per app session. */
export function getConfig(): Promise<AppConfig> {
  if (!configPromise) {
    configPromise = (async () => {
      // `npm run dev` in a plain browser has no Rust side; an unconfigured
      // config reads as "offline", which the sync paths already handle.
      if (!inTauri()) return BROWSER_FALLBACK;
      try {
        return JSON.parse(await invoke<string>("get_config")) as AppConfig;
      } catch (e) {
        console.error("getConfig failed:", e);
        return BROWSER_FALLBACK;
      }
    })();
  }
  return configPromise;
}

/**
 * Forget the memoized config, so the next getConfig() re-reads the file.
 *
 * Required after anything that writes the config from Rust -- keygen and the
 * cloud deploy -- or the UI keeps serving the config captured at app start.
 */
function invalidateConfig(): void {
  configPromise = null;
}

/** Upsert KEY=VALUE pairs into the config file. Takes effect on restart. */
export async function setConfig(values: Record<string, string>): Promise<void> {
  const pairs = Object.entries(values).map(([k, v]) => `${k}=${v}`);
  if (!pairs.length) return;
  await invoke("set_config", { pairs });
  // Drop the memo so a later read in this session sees the new values, even
  // though the DB/sync clients built from them still need a restart.
  invalidateConfig();
}

export interface DoctorReport {
  ready: boolean;
  checks: Record<string, boolean>;
}

/**
 * Environment readiness: getConfig()'s config-derived checks plus the two that
 * need the database or the Worker.
 */
export async function runDoctor(): Promise<DoctorReport> {
  const cfg = await getConfig();
  const [{ historyHasData }, tokensValid] = await Promise.all([
    import("./db").then((m) => m.readinessChecks()),
    hasStoredTokens(cfg),
  ]);

  const checks: Record<string, boolean> = {
    ...cfg.checks,
    tokens_valid: tokensValid,
    history_has_data: historyHasData,
  };

  // history_has_data is not required: an empty dashboard is a valid state to
  // finish setup in, since the Spotify export takes days to arrive.
  const ready = !!(checks.client_id && checks.fernet_key && checks.tokens_valid);
  return { ready, checks };
}

/**
 * Whether D1 already holds a token row for the configured user.
 *
 * Asks the Worker, not a local file: OAuth writes tokens straight to D1 and this
 * machine keeps no copy. Never throws — offline reads as "not authorized", which
 * is the same thing the Setup page needs to show.
 */
async function hasStoredTokens(cfg: AppConfig): Promise<boolean> {
  if (!cfg.configured.worker) return false;
  try {
    const { fetch } = await import("@tauri-apps/plugin-http");
    const res = await fetch(
      `${cfg.worker_url}/api/tokens?user_id=${encodeURIComponent(cfg.spotify_user_id)}`,
      { headers: { Authorization: `Bearer ${cfg.worker_auth_token}` } }
    );
    if (!res.ok) return false; // 404 is the documented "no row" answer
    const row = (await res.json()) as { refresh_token?: string };
    return !!row.refresh_token;
  } catch (e) {
    console.debug("hasStoredTokens failed:", e);
    return false;
  }
}

/** Create TOKEN_ENCRYPT_KEY if absent. Never rotates an existing one. */
export async function keygen(): Promise<void> {
  try {
    await invoke("keygen");
  } finally {
    invalidateConfig();
  }
}

/**
 * Deploy the Cloudflare backend. Resolves when the deploy finishes (minutes);
 * progress arrives as `cloud-log` events, not as a return value.
 */
export async function cloudDeploy(
  name: string,
  apiToken: string,
  rotate = false,
): Promise<void> {
  try {
    return await invoke("cloud_deploy", { name, apiToken, rotate });
  } finally {
    // The deploy wrote WORKER_URL/WORKER_AUTH_TOKEN itself. Also on failure:
    // it may have got far enough to write them before dying.
    invalidateConfig();
  }
}

/** Folder picker for the Spotify history export. Null when cancelled. */
export async function pickHistoryFolder(): Promise<string | null> {
  return invoke<string | null>("pick_history_folder");
}
