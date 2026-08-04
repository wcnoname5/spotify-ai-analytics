// The batched INSERT, checked against a real SQLite. A wrong placeholder scheme
// here inserts N copies of one play with no error to notice, so asserting on the
// generated string alone would not be enough.
import { DatabaseSync } from "node:sqlite";
import { describe, expect, it } from "vitest";

import insertTrackSql from "@sql/insert_track.sql?raw";
import { multiRowInsert } from "./sync";
import { migrate, statements } from "./migrations";

async function migrated(): Promise<DatabaseSync> {
  const db = new DatabaseSync(":memory:");
  const adapter = {
    execute: async (sql: string) => {
      db.exec(sql);
      return { rowsAffected: 0, lastInsertId: 0 };
    },
    select: async (sql: string) => db.prepare(sql).all(),
  } as unknown as Parameters<typeof migrate>[0];
  await migrate(adapter);
  return db;
}

const play = (id: string, playedAt: string) => [
  id,
  "spotify:track:x",
  "Song",
  "Artist",
  "Album",
  playedAt,
  1000,
  "api",
  null,
  null,
  null,
  null,
  null,
  null,
];

describe("multiRowInsert", () => {
  it("keeps the shared column list", () => {
    const sql = multiRowInsert(2);
    for (const column of ["track_id", "played_at", "ms_played", "shuffle", "skipped"]) {
      expect(sql).toContain(column);
    }
    expect(sql).toContain("INSERT OR IGNORE");
  });

  it("emits positional placeholders, never the numbered ones", () => {
    // `?1 … ?14` repeated per row would bind the same values to every row.
    expect(insertTrackSql).toMatch(/\?1\b/);
    expect(multiRowInsert(3)).not.toMatch(/\?\d/);
  });

  it("emits one placeholder group per row, matching the source arity", () => {
    const arity = (insertTrackSql.split(/VALUES/i)[1].match(/\?/g) ?? []).length;
    expect(arity).toBe(14);
    expect((multiRowInsert(5).match(/\?/g) ?? []).length).toBe(arity * 5);
  });

  it("rejects a template it no longer understands", () => {
    expect(() => multiRowInsert(2, "SELECT 1")).toThrow(/insert_track/);
  });

  it("inserts distinct rows, not N copies of the first", async () => {
    const db = await migrated();
    const rows = [play("a", "2026-01-01T00:00:00Z"), play("b", "2026-01-02T00:00:00Z"), play("c", "2026-01-03T00:00:00Z")];
    db.prepare(multiRowInsert(rows.length)).run(...rows.flat());

    const got = db.prepare("SELECT id, played_at FROM listening_history ORDER BY id").all() as {
      id: string;
      played_at: string;
    }[];
    expect(got.map((r) => r.id)).toEqual(["a", "b", "c"]);
    expect(got[0].played_at).toBe("2026-01-01T00:00:00Z");
    expect(got[2].played_at).toBe("2026-01-03T00:00:00Z");
  });

  it("is idempotent, so a re-synced page inserts nothing", async () => {
    const db = await migrated();
    const rows = [play("a", "2026-01-01T00:00:00Z"), play("b", "2026-01-02T00:00:00Z")];
    const sql = multiRowInsert(rows.length);

    db.prepare(sql).run(...rows.flat());
    const second = db.prepare(sql).run(...rows.flat());

    expect(second.changes).toBe(0);
    const count = db.prepare("SELECT COUNT(*) AS n FROM listening_history").get() as { n: number };
    expect(count.n).toBe(2);
  });

  it("stays inside SQLite's 999-parameter limit at the chunk size used", () => {
    // 14 columns x 60 rows = 840. A larger chunk would fail only on a full page,
    // i.e. only during a first sync against a big history.
    expect((multiRowInsert(60).match(/\?/g) ?? []).length).toBeLessThan(999);
  });
});

describe("statements()", () => {
  it("handles the shared insert file without mangling it", () => {
    expect(statements(insertTrackSql)).toHaveLength(1);
  });
});
