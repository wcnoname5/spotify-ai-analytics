// Run against a real SQLite (node:sqlite), not a fake: the thing being tested is
// whether a *database* ends up correct, and a mock that records statements would
// pass while the SQL was wrong.
//
// This is the highest-value test in the codebase. Every other failure shows up on
// the developer's machine; this one shows up on an already-installed user's
// machine, at update time, as data that quietly stopped appearing.
import { DatabaseSync } from "node:sqlite";
import { beforeEach, describe, expect, it } from "vitest";

import { migrate, migrations, statements } from "./migrations";

/** The subset of @tauri-apps/plugin-sql's Database that migrate() uses. */
function adapt(db: DatabaseSync) {
  return {
    execute: async (sql: string) => {
      db.exec(sql);
      return { rowsAffected: 0, lastInsertId: 0 };
    },
    select: async (sql: string) => db.prepare(sql).all(),
  } as unknown as Parameters<typeof migrate>[0];
}

const version = (db: DatabaseSync) =>
  (db.prepare("PRAGMA user_version").get() as { user_version: number }).user_version;

const tables = (db: DatabaseSync) =>
  new Set(
    (db.prepare("SELECT name FROM sqlite_master WHERE type='table'").all() as { name: string }[])
      .map((r) => r.name)
  );

describe("migrations()", () => {
  it("finds the shared migration files, in filename order", () => {
    const names = migrations().map(([name]) => name);
    expect(names.length).toBeGreaterThanOrEqual(2);
    expect(names[0]).toBe("0001_init.sql");
    expect([...names]).toEqual([...names].sort());
  });

  it("carries real SQL, not empty strings from a bad glob", () => {
    // A misconfigured `import.meta.glob` yields the right keys and empty values,
    // which would migrate a database to "version 2" with no tables in it.
    for (const [name, sql] of migrations()) {
      expect(sql.length, `${name} is empty`).toBeGreaterThan(50);
      expect(sql).toContain("CREATE");
    }
  });
});

describe("statements()", () => {
  it("drops comments before splitting, since comments contain semicolons", () => {
    const sql = `
      -- a comment; with a semicolon
      CREATE TABLE a (x TEXT); -- trailing; comment
      CREATE TABLE b (y TEXT);
    `;
    expect(statements(sql)).toEqual(["CREATE TABLE a (x TEXT)", "CREATE TABLE b (y TEXT)"]);
  });

  it("ignores trailing whitespace and empty statements", () => {
    expect(statements("CREATE TABLE a (x TEXT);;\n\n  ")).toEqual(["CREATE TABLE a (x TEXT)"]);
  });
});

describe("migrate()", () => {
  let db: DatabaseSync;

  beforeEach(() => {
    db = new DatabaseSync(":memory:");
  });

  it("takes a fresh database to the latest version", async () => {
    const result = await migrate(adapt(db));

    expect(result.from).toBe(0);
    expect(result.to).toBe(migrations().length);
    expect(result.applied).toEqual(migrations().map(([n]) => n));
    expect(version(db)).toBe(migrations().length);
    expect(tables(db)).toContain("listening_history");
    expect(tables(db)).toContain("reports");
  });

  it("is a no-op the second time", async () => {
    await migrate(adapt(db));
    const second = await migrate(adapt(db));

    expect(second.from).toBe(migrations().length);
    expect(second.applied).toEqual([]);
  });

  it("applies only what is new when partly migrated", async () => {
    // The v1.1-over-v1 case: an installed user sitting on an older version.
    const all = migrations();
    for (const statement of statements(all[0][1])) db.exec(statement);
    db.exec("PRAGMA user_version = 1");

    const result = await migrate(adapt(db));

    expect(result.from).toBe(1);
    expect(result.applied).toEqual(all.slice(1).map(([n]) => n));
    expect(version(db)).toBe(all.length);
  });

  it("does not touch existing rows", async () => {
    // The whole point. An upgrade that dropped the user's cached history would
    // be recoverable (it re-syncs from D1) but would look like data loss.
    await migrate(adapt(db));
    db.exec(
      "INSERT INTO listening_history (id, track_id, played_at) " +
        "VALUES ('abc', 'spotify:track:1', '2026-01-01T00:00:00Z')"
    );
    db.exec("PRAGMA user_version = 1"); // pretend an older build wrote this

    await migrate(adapt(db));

    const rows = db.prepare("SELECT id FROM listening_history").all() as { id: string }[];
    expect(rows).toHaveLength(1);
    expect(rows[0].id).toBe("abc");
  });

  it("leaves the version behind when a migration throws, so it is retried", async () => {
    const broken = {
      execute: async (sql: string) => {
        if (sql.startsWith("PRAGMA user_version")) throw new Error("boom");
        db.exec(sql);
        return { rowsAffected: 0, lastInsertId: 0 };
      },
      select: async (sql: string) => db.prepare(sql).all(),
    } as unknown as Parameters<typeof migrate>[0];

    await expect(migrate(broken)).rejects.toThrow("boom");
    // Still 0, so the next open re-applies. Safe only because every statement is
    // idempotent — see the note in migrate().
    expect(version(db)).toBe(0);
    await migrate(adapt(db));
    expect(version(db)).toBe(migrations().length);
  });

  it("produces a schema the app's own queries run against", async () => {
    // Guards the case where migrations apply cleanly but describe a schema the
    // rest of the code does not expect.
    await migrate(adapt(db));
    expect(() =>
      db.prepare("SELECT MAX(played_at) FROM listening_history").get()
    ).not.toThrow();
    expect(() =>
      db.prepare("SELECT id FROM reports WHERE synced = 0").all()
    ).not.toThrow();
    expect(() => db.prepare("SELECT value FROM sync_state WHERE key = ?").get("k")).not.toThrow();
  });
});
