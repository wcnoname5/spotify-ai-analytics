// Schema versioning for the local SQLite cache.
//
// Before this, db.ts re-ran `schema.sql`'s `CREATE TABLE IF NOT EXISTS` on every
// open. That works exactly once: it creates a missing database and then does
// nothing forever. Ship a v1.1 that adds a column and every already-installed
// user keeps the v1 schema, silently, because IF NOT EXISTS has no opinion about
// tables that exist but are wrong.
//
// `PRAGMA user_version` is a 4-byte integer SQLite stores in the database header.
// It costs no table, no bookkeeping, and it is the standard way to do this.
//
// The migrations are the same numbered files applied to D1
// (packages/core/spotify_core/db/sql/migrations/), so local and remote cannot
// drift apart.
import type Database from "@tauri-apps/plugin-sql";

// Eager glob: these end up in the bundle as strings, which is what we want —
// a packaged app has no filesystem to read them from.
const FILES = import.meta.glob("@sql/migrations/*.sql", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

/** `[filename, sql]`, in filename order. The numeric prefix *is* the version. */
export function migrations(): [string, string][] {
  return Object.entries(FILES)
    .map(([path, sql]) => [path.split("/").pop() ?? path, sql] as [string, string])
    .sort(([a], [b]) => a.localeCompare(b));
}

/**
 * Split one migration into statements.
 *
 * Comments are stripped first because they contain semicolons. Naive, and
 * correct only while migrations hold plain DDL — a trigger body or a string
 * literal containing `;` breaks it. That is the point to reach for a real
 * parser rather than a cleverer regex; until then, failing loudly on the next
 * `db.execute` beats a silent half-applied migration.
 */
export function statements(sql: string): string[] {
  return sql
    .split("\n")
    .map((line) => line.split("--")[0])
    .join("\n")
    .split(";")
    .map((s) => s.trim())
    .filter(Boolean);
}

export interface MigrationResult {
  from: number;
  to: number;
  applied: string[];
}

/**
 * Bring `db` up to the latest schema version.
 *
 * Each migration runs to completion before `user_version` advances, so a crash
 * mid-file leaves the version behind and the whole file is retried on next open.
 * That is safe *because* every statement is idempotent; a migration that is not
 * would need a transaction here, which sqlx's connection pool makes awkward
 * (see the note in sync.ts about COMMIT landing on a different connection).
 */
export async function migrate(db: Database): Promise<MigrationResult> {
  const rows = await db.select<{ user_version: number }[]>("PRAGMA user_version");
  const from = rows[0]?.user_version ?? 0;
  const all = migrations();
  const applied: string[] = [];

  for (const [index, [name, sql]] of all.entries()) {
    const version = index + 1;
    if (version <= from) continue;

    for (const statement of statements(sql)) {
      await db.execute(statement);
    }
    // Not a bound parameter: SQLite does not accept one in a PRAGMA. `version`
    // is a loop index over a compile-time file list, never user input.
    await db.execute(`PRAGMA user_version = ${version}`);
    applied.push(name);
  }

  return { from, to: all.length, applied };
}
