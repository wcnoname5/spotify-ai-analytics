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
