// Local SQLite cache access via tauri-plugin-sql (sqlx). This is a pull-only
// mirror of D1 — never write here except through sync.ts's INSERT OR IGNORE.
import Database from "@tauri-apps/plugin-sql";
import schemaSql from "@sql/schema.sql?raw";

export const isTauri = "__TAURI_INTERNALS__" in window;

let dbPromise: Promise<Database> | null = null;

/** Memoized handle to the local history.db, schema applied on first load. */
export function getDb(): Promise<Database> {
  if (!dbPromise) {
    dbPromise = (async () => {
      const db = await Database.load("sqlite:" + __HISTORY_DB_PATH__);
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
