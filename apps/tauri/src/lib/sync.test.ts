// The batched INSERT, checked against a real SQLite. A wrong placeholder scheme
// here inserts N copies of one play with no error to notice, so asserting on the
// generated string alone would not be enough.
import { DatabaseSync } from "node:sqlite";
import { beforeEach, describe, expect, it, vi } from "vitest";

import insertTrackSql from "@sql/insert_track.sql?raw";
import { deleteReport, multiRowInsert, syncOnStartup } from "./sync";
import { migrate, statements } from "./migrations";

// The startup sync's collaborators are all Tauri plugins; only the cursor
// decision is under test here.
const fetchMock = vi.fn();
vi.mock("@tauri-apps/plugin-http", () => ({
  fetch: (...args: unknown[]) => fetchMock(...args),
}));
vi.mock("./config", () => ({
  getConfig: async () => ({ worker_url: "https://w.example", worker_auth_token: "t" }),
}));
const dbStub = { select: vi.fn(), execute: vi.fn() };
vi.mock("./db", () => ({ getDb: async () => dbStub }));

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

describe("syncOnStartup cursor", () => {
  const LOCAL_MAX = "2026-01-05T00:00:00Z";

  /** Answer the count endpoint with `remote`, then hand back one empty page. */
  function arrange(localCount: number, remoteCount: number) {
    dbStub.select.mockImplementation(async (sql: string) =>
      /COUNT/i.test(sql) ? [{ n: localCount }] : [{ c: LOCAL_MAX }]
    );
    fetchMock.mockImplementation(async (url: string) => ({
      ok: true,
      json: async () =>
        url.includes("/count") ? { count: remoteCount } : { tracks: [] },
    }));
  }

  const tracksUrl = () =>
    fetchMock.mock.calls.map((c) => String(c[0])).find((u) => !u.includes("/count"));

  beforeEach(() => {
    dbStub.select.mockReset();
    dbStub.execute.mockReset();
    fetchMock.mockReset();
  });

  it("stays incremental when the counts agree", async () => {
    arrange(10, 10);
    await syncOnStartup();
    expect(tracksUrl()).toContain(encodeURIComponent(LOCAL_MAX));
  });

  it("backfills from the epoch when D1 holds rows the cursor cannot reach", async () => {
    // The export-import case: 50 recent plays locally, years of history in D1.
    arrange(50, 90000);
    await syncOnStartup();
    expect(tracksUrl()).toContain(encodeURIComponent("1970-01-01T00:00:00Z"));
  });

  it("stays incremental when the count check fails", async () => {
    dbStub.select.mockImplementation(async () => [{ c: LOCAL_MAX }]);
    fetchMock.mockImplementation(async (url: string) =>
      url.includes("/count")
        ? { ok: false, status: 500 }
        : { ok: true, json: async () => ({ tracks: [] }) }
    );
    await syncOnStartup();
    expect(tracksUrl()).toContain(encodeURIComponent(LOCAL_MAX));
  });
});

describe("deleteReport", () => {
  // The ordering IS the feature: local-first would let the MAX(generated_at)
  // pull cursor resurrect the row from D1 on the next startup.
  beforeEach(() => {
    dbStub.select.mockReset();
    dbStub.execute.mockReset();
    fetchMock.mockReset();
  });

  it("deletes D1 first, then the local row", async () => {
    fetchMock.mockResolvedValue({ ok: true, json: async () => ({ deleted: 1 }) });
    await deleteReport("abc");

    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api/reports?id=abc");
    expect((init as { method: string }).method).toBe("DELETE");
    expect(dbStub.execute).toHaveBeenCalledTimes(1);
    expect(String(dbStub.execute.mock.calls[0][0])).toMatch(/DELETE FROM reports/i);
    expect(dbStub.execute.mock.calls[0][1]).toEqual(["abc"]);
  });

  it("leaves the local row alone when the Worker refuses", async () => {
    fetchMock.mockResolvedValue({ ok: false, status: 502 });
    await expect(deleteReport("abc")).rejects.toThrow(/502/);
    expect(dbStub.execute).not.toHaveBeenCalled();
  });

  it("still drops the local row when D1 never had it", async () => {
    fetchMock.mockResolvedValue({ ok: true, json: async () => ({ deleted: 0 }) });
    await deleteReport("gone");
    expect(dbStub.execute).toHaveBeenCalledTimes(1);
  });
});

describe("statements()", () => {
  it("handles the shared insert file without mangling it", () => {
    expect(statements(insertTrackSql)).toHaveLength(1);
  });
});
