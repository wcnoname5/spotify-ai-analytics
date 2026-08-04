// Runtime config, read from the Rust side (src-tauri/src/config.rs), which owns
// the config file and its path resolution.
//
// This used to spawn `uv run spotify-mcp config get` -- ~1.7s per read, and
// impossible in a packaged build, which has no `uv` and no repo checkout. The
// resolution rule is now a single environment variable (SPOTIFY_CONFIG), so
// there is one implementation and it cannot depend on the launch directory.
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
  langsmith: boolean;
  worker: boolean;
}

export interface AppConfig {
  env_file: string;
  dev: boolean;
  history_db_path: string;
  worker_url: string;
  worker_auth_token: string;
  configured: ConfiguredFlags;
  /** Config-derived readiness checks. DB-derived ones are added by runDoctor. */
  checks: Record<string, boolean>;
}

const BROWSER_FALLBACK: AppConfig = {
  env_file: "",
  dev: false,
  history_db_path: "",
  worker_url: "",
  worker_auth_token: "",
  configured: {
    client_id: false, gemini: false, openai: false, langfuse: false, langsmith: false, worker: false,
  },
  checks: {},
};

let configPromise: Promise<AppConfig> | null = null;

/** Memoized runtime config. One spawn per app session. */
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
 * Forget the memoized config, so the next getConfig() re-reads the .env.
 *
 * Required after anything that writes the .env from *outside* this module --
 * `cloud deploy` writes WORKER_URL/WORKER_AUTH_TOKEN from Python, and without
 * this the UI keeps serving the config captured at app start and never notices
 * the Worker exists.
 */
export function invalidateConfig(): void {
  configPromise = null;
}

/** Upsert KEY=VALUE pairs into the resolved .env. Takes effect on restart. */
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
  actions_needed: string[];
  message: string;
  warnings: string[];
}

/**
 * Environment readiness.
 *
 * This used to be a second ~1.7s Python spawn (`spotify-mcp doctor --json`).
 * The config-derived half now rides along in getConfig(); the two DB-derived
 * checks are queried here, through the SQLite handle the dashboard already has.
 *
 * `dbs_initialized` is gone as a check: getDb() applies the schema on open, so
 * it could only ever report true by the time anything could ask.
 */
export async function runDoctor(): Promise<DoctorReport> {
  const cfg = await getConfig();
  const { historyHasData, tokensValid } = await import("./db").then((m) => m.readinessChecks());

  const checks: Record<string, boolean> = {
    ...cfg.checks,
    tokens_valid: tokensValid,
    history_has_data: historyHasData,
  };

  const actions_needed: string[] = [];
  if (!checks.client_id) actions_needed.push("Enter your Spotify Client ID above.");
  if (!checks.fernet_key) actions_needed.push("Generate an encryption key.");
  if (!checks.tokens_valid) actions_needed.push("Authorize Spotify.");
  // Non-blocking: an empty dashboard is a valid state to finish setup in, since
  // the Spotify export takes days to arrive.
  if (!checks.history_has_data) actions_needed.push("Import or fetch some listening history.");

  const blocking = actions_needed.filter((a) => !a.startsWith("Import or fetch"));
  return {
    ready: blocking.length === 0,
    checks,
    actions_needed,
    message: actions_needed.length ? `${actions_needed.length} action(s) required.` : "All set.",
    // The old warnings were all about two .env files disagreeing. There is one
    // config file now, at one resolved path, so the condition cannot arise.
    warnings: [],
  };
}

export type SetupStep = "oauth" | "import" | "sync";

/** Run a whitelisted setup step. Buffered: resolves when the step finishes. */
export async function runSetupStep(step: SetupStep, arg?: string): Promise<string> {
  try {
    return await invoke<string>("run_setup_step", { step, arg: arg ?? null });
  } finally {
    invalidateConfig();
  }
}

/** Create TOKEN_ENCRYPT_KEY if absent. Never rotates an existing one. */
export async function keygen(): Promise<{ created: boolean }> {
  try {
    return JSON.parse(await invoke<string>("keygen")) as { created: boolean };
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
