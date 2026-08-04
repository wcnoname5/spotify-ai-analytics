// Local SQLite cache access via tauri-plugin-sql (sqlx).
// most tables are pull-only mirror of D1, never write here except through sync.ts's INSERT OR IGNORE.
// reports is an exception, it is written locally first (synced=0) via queries.ts's saveReportLocal, then pushed to D1 afterwards.
import Database from "@tauri-apps/plugin-sql";
import { getConfig } from "./config";
import { migrate } from "./migrations";

// Guarded rather than a bare `in window`: this module is imported by code that
// also runs outside a DOM (unit tests), where the bare form throws at import time.
export const isTauri = typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

let dbPromise: Promise<Database> | null = null;

/** Memoized handle to the local history.db, migrated to the current schema. */
export function getDb(): Promise<Database> {
  if (!dbPromise) {
    dbPromise = (async () => {
      const { history_db_path } = await getConfig();
      const db = await Database.load("sqlite:" + history_db_path.replace(/\\/g, "/"));
      const result = await migrate(db);
      if (result.applied.length) {
        console.info(`schema ${result.from} -> ${result.to}:`, result.applied.join(", "));
      }
      await db.execute("PRAGMA journal_mode=WAL");
      return db;
    })();
  }
  return dbPromise;
}

/**
 * The readiness check that needs the database rather than the config file.
 *
 * Inline SQL rather than a shared `sql/` file: the shared module exists so the
 * Python and TS query paths cannot drift, and this has no Python caller.
 *
 * Never throws. Setup runs on machines where the DB may not exist yet, and a
 * missing file has to read as "not done", not as a crash.
 */
export async function readinessChecks(): Promise<{ historyHasData: boolean }> {
  try {
    const db = await getDb();
    const rows = await db.select<{ n: number }[]>(
      "SELECT COUNT(*) AS n FROM listening_history"
    );
    return { historyHasData: (rows[0]?.n ?? 0) > 0 };
  } catch (e) {
    console.error("readinessChecks: history check failed:", e);
    return { historyHasData: false };
  }
}
