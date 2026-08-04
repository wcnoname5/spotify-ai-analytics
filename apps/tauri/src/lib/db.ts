// Local SQLite cache access via tauri-plugin-sql (sqlx).
// most tables are pull-only mirror of D1, never write here except through sync.ts's INSERT OR IGNORE.
// reports is an exception, it is written locally first (synced=0) via queries.ts's saveReportLocal, then pushed to D1 afterwards.
import Database from "@tauri-apps/plugin-sql";
import schemaSql from "@sql/schema.sql?raw";
import { getConfig } from "./config";

export const isTauri = "__TAURI_INTERNALS__" in window;

let dbPromise: Promise<Database> | null = null;

/** Memoized handle to the local history.db, schema applied on first load. */
export function getDb(): Promise<Database> {
  if (!dbPromise) {
    dbPromise = (async () => {
      const { history_db_path } = await getConfig();
      const db = await Database.load("sqlite:" + history_db_path.replace(/\\/g, "/"));
      // schema.sql statements are idempotent (CREATE TABLE/INDEX IF NOT EXISTS).
      // Strip `--` comment tails before splitting on `;`
      const withoutComments = schemaSql
        .split("\n")
        .map((line) => line.split("--")[0])
        .join("\n");
      for (const statement of withoutComments.split(";").map((s) => s.trim()).filter(Boolean)) {
        await db.execute(statement);
      }
      await db.execute("PRAGMA journal_mode=WAL");
      return db;
    })();
  }
  return dbPromise;
}

/**
 * The two readiness checks that need a database rather than the config file.
 *
 * Inline SQL rather than a shared `sql/` file: the shared module exists so the
 * Python and TS query paths cannot drift, and these two have no Python caller —
 * `spotify-mcp doctor` is gone.
 *
 * Never throws. Setup runs on machines where these DBs may not exist yet, and a
 * missing file has to read as "not done", not as a crash.
 */
export async function readinessChecks(): Promise<{
  historyHasData: boolean;
  tokensValid: boolean;
}> {
  let historyHasData = false;
  try {
    const db = await getDb();
    const rows = await db.select<{ n: number }[]>(
      "SELECT COUNT(*) AS n FROM listening_history"
    );
    historyHasData = (rows[0]?.n ?? 0) > 0;
  } catch (e) {
    console.error("readinessChecks: history check failed:", e);
  }

  let tokensValid = false;
  try {
    const { history_db_path } = await getConfig();
    // tokens.db sits beside history.db. ponytail: this whole check goes when
    // OAuth writes straight to D1 and the local tokens.db stops existing —
    // it becomes `GET /api/tokens`.
    const tokensPath = history_db_path.replace(/history\.db$/, "tokens.db");
    const tokensDb = await Database.load("sqlite:" + tokensPath.replace(/\\/g, "/"));
    const rows = await tokensDb.select<{ n: number }[]>(
      "SELECT COUNT(*) AS n FROM spotify_tokens WHERE refresh_token != ''"
    );
    tokensValid = (rows[0]?.n ?? 0) > 0;
  } catch (e) {
    // Includes "no such table" on a DB the OAuth step has never written to.
    console.debug("readinessChecks: token check failed:", e);
  }

  return { historyHasData, tokensValid };
}
