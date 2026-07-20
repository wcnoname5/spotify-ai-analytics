// Runtime config, replacing the build-time Vite `define` constants.
//
// Resolution (DEV vs platformdirs, HISTORY_DB_PATH precedence) lives in Python
// -- paths.py + config.Settings -- and is read here via `spotify-mcp config get`.
// Reimplementing it in TS/Rust is what produced the twin-.env problem before.
//
// Changes written by set_config apply on restart: rebuilding the DB handle and
// sync client mid-session is not worth it for a value edited a few times ever.
import { invoke } from "@tauri-apps/api/core";

// Checked inline rather than imported from db.ts: db.ts imports this module,
// and the cycle would be resolved at module-init time.
const inTauri = () => "__TAURI_INTERNALS__" in window;

export interface AppConfig {
  env_file: string;
  dev: boolean;
  history_db_path: string;
  worker_url: string;
  worker_auth_token: string;
}

const BROWSER_FALLBACK: AppConfig = {
  env_file: "",
  dev: false,
  history_db_path: "",
  worker_url: "",
  worker_auth_token: "",
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

/** Upsert KEY=VALUE pairs into the resolved .env. Takes effect on restart. */
export async function setConfig(values: Record<string, string>): Promise<void> {
  const pairs = Object.entries(values).map(([k, v]) => `${k}=${v}`);
  if (!pairs.length) return;
  await invoke("set_config", { pairs });
  // Drop the memo so a later read in this session sees the new values, even
  // though the DB/sync clients built from them still need a restart.
  configPromise = null;
}

export interface DoctorReport {
  ready: boolean;
  checks: Record<string, boolean>;
  actions_needed: string[];
  message: string;
  warnings: string[];
}

/** Environment readiness. Non-zero exit is normal mid-setup and is ignored. */
export async function runDoctor(): Promise<DoctorReport> {
  return JSON.parse(await invoke<string>("doctor")) as DoctorReport;
}

export type SetupStep = "oauth" | "keygen" | "import";

/** Run a whitelisted setup step. Buffered: resolves when the step finishes. */
export async function runSetupStep(step: SetupStep, arg?: string): Promise<string> {
  return invoke<string>("run_setup_step", { step, arg: arg ?? null });
}

/** Folder picker for the Spotify history export. Null when cancelled. */
export async function pickHistoryFolder(): Promise<string | null> {
  return invoke<string | null>("pick_history_folder");
}
