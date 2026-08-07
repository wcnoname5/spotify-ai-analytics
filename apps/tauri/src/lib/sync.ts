// Startup incremental sync: Worker (D1) <-> local SQLite mirror. Tracks are pull-only;
// reports are locally-written (Save to DB) and pushed to D1 here, then pulled back.
import maxPlayedAtSql from "@sql/max_played_at.sql?raw";
import insertTrackSql from "@sql/insert_track.sql?raw";
import insertReportSql from "@sql/insert_report.sql?raw";
import unsyncedReportsSql from "@sql/unsynced_reports.sql?raw";
import markReportSyncedSql from "@sql/mark_report_synced.sql?raw";
import maxReportGeneratedAtSql from "@sql/max_report_generated_at.sql?raw";
// Rust-side fetch: webview fetch enforces CORS, the Worker sends no CORS headers.
import { fetch } from "@tauri-apps/plugin-http";
import { getDb } from "./db";
import { getConfig } from "./config";
import { deleteReportLocal } from "./queries";
import type { TrackRow } from "./api";

const EPOCH = "1970-01-01T00:00:00Z";

export type SyncResult =
  | { inserted: number }
  | { offline: true; reason: "unconfigured" | "error" };

/**
 * Rows per INSERT.
 *
 * Inserting one row per `db.execute` meant one IPC round trip per play — tens of
 * thousands of them after an export import, which took minutes. A multi-row
 * VALUES cuts that by ~100x. Not larger: SQLite's default limit is 999 bound
 * parameters, and each row binds 14.
 */
const INSERT_CHUNK = 60;

/** One page of tracks from the Worker. */
interface TrackPage {
  tracks: TrackRow[];
  next_since?: string;
  next_id?: string;
}

export async function syncOnStartup(): Promise<SyncResult> {
  const { worker_url, worker_auth_token } = await getConfig();
  if (!worker_url) return { offline: true, reason: "unconfigured" };

  try {
    const db = await getDb();
    const cursorRows = await db.select<{ c: string | null }[]>(maxPlayedAtSql);
    let since = cursorRows[0]?.c ?? EPOCH;
    let sinceId: string | undefined;
    let inserted = 0;

    if (since !== EPOCH && (await isBehind(db, worker_url, worker_auth_token))) {
      since = EPOCH;
    }

    // Loop until the Worker stops handing back a cursor. It caps each page, so a
    // first sync against a full imported history is many small responses rather
    // than one that blows the Worker's 128 MB budget.
    for (;;) {
      const query = new URLSearchParams({ since });
      if (sinceId !== undefined) query.set("since_id", sinceId);

      const res = await fetch(`${worker_url}/api/tracks?${query}`, {
        headers: { Authorization: `Bearer ${worker_auth_token}` },
      });
      if (!res.ok) {
        console.error(`syncOnStartup: worker responded ${res.status}`);
        // Whatever landed already is kept: the next run resumes from the new
        // MAX(played_at) rather than starting over.
        return inserted ? { inserted } : { offline: true, reason: "error" };
      }

      const page = (await res.json()) as TrackPage;
      inserted += await insertTracks(db, page.tracks ?? []);

      if (!page.next_since) return { inserted };
      since = page.next_since;
      sinceId = page.next_id;
    }
  } catch (e) {
    console.error("syncOnStartup failed:", e);
    return { offline: true, reason: "error" };
  }
}

/**
 * Is the local mirror missing rows the cursor can never reach?
 *
 * The cursor only moves forward, so a row landing in D1 *older* than the local
 * MAX(played_at) is invisible to an incremental sync — permanently. That is the
 * normal case, not an edge one: authorizing pulls the last ~50 plays, then the
 * Spotify export arrives days later and imports years of older history.
 *
 * Row counts are the cheap way to notice. `<`, not `!==`: rows deleted from D1
 * would otherwise make every startup re-scan and never reconcile.
 *
 * Any failure answers "no" — a full re-pull is the expensive branch, and being
 * offline is not evidence of a gap.
 */
async function isBehind(
  db: Awaited<ReturnType<typeof getDb>>,
  workerUrl: string,
  token: string
): Promise<boolean> {
  try {
    const res = await fetch(`${workerUrl}/api/tracks/count`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) return false;
    const { count } = (await res.json()) as { count?: number };
    if (typeof count !== "number") return false;

    const rows = await db.select<{ n: number }[]>(
      "SELECT COUNT(*) AS n FROM listening_history"
    );
    const local = rows[0]?.n ?? 0;
    if (local >= count) return false;
    console.info(`sync: local ${local} rows vs D1 ${count} — backfilling from the epoch`);
    return true;
  } catch (e) {
    console.error("sync: row-count check failed, staying incremental:", e);
    return false;
  }
}

/**
 * Insert a batch of tracks, chunked into multi-row INSERTs.
 *
 * No BEGIN/COMMIT: sqlx pooling can route COMMIT to a different connection.
 * INSERT OR IGNORE is idempotent, so a partial sync just re-pulls from the same
 * cursor next time.
 */
async function insertTracks(
  db: Awaited<ReturnType<typeof getDb>>,
  tracks: TrackRow[]
): Promise<number> {
  let inserted = 0;
  for (let i = 0; i < tracks.length; i += INSERT_CHUNK) {
    const chunk = tracks.slice(i, i + INSERT_CHUNK);
    const values: unknown[] = [];
    for (const t of chunk) {
      values.push(
        t.id,
        t.track_id,
        t.track_name ?? null,
        t.artist_name ?? null,
        t.album_name ?? null,
        t.played_at,
        t.ms_played ?? null,
        t.source ?? null,
        t.platform ?? null,
        t.conn_country ?? null,
        t.reason_start ?? null,
        t.reason_end ?? null,
        t.shuffle ?? null,
        t.skipped ?? null
      );
    }
    const result = await db.execute(multiRowInsert(chunk.length), values);
    inserted += result.rowsAffected;
  }
  return inserted;
}

/**
 * Widen the shared single-row INSERT to `count` rows.
 *
 * The column list and arity come from `insert_track.sql` rather than being
 * written out again here: a column added to the shared file but not to a copy is
 * silent data loss, not an error.
 *
 * The placeholders are regenerated as positional `?` rather than reused. The
 * source uses numbered parameters (`?1 … ?14`), and repeating that clause would
 * bind the same values to every row — inserting `count` copies of one play, with
 * no error to notice.
 */
export function multiRowInsert(count: number, template = insertTrackSql): string {
  const [head, tail] = template.split(/VALUES/i);
  const arity = (tail?.match(/\?/g) ?? []).length;
  if (!head || arity === 0) {
    throw new Error("insert_track.sql no longer looks like `... VALUES (?, ...)`");
  }
  const row = `(${Array.from({ length: arity }, () => "?").join(", ")})`;
  return `${head.trim()} VALUES ${Array.from({ length: count }, () => row).join(", ")}`;
}

export interface ReportRow {
  id: string; style: string; period_type: string;
  start_date: string; end_date: string; provider: string; model: string;
  generated_at: string; revision_count: number; report_text: string;
}

/** Push local synced=0 report rows, then pull D1 rows behind the generated_at cursor. */
export async function syncReports(): Promise<{ pushed: number; pulled: number } | { offline: true }> {
  const { worker_url, worker_auth_token } = await getConfig();
  if (!worker_url) return { offline: true };
  try {
    const db = await getDb();
    const auth = { Authorization: `Bearer ${worker_auth_token}` };

    const unsynced = await db.select<ReportRow[]>(unsyncedReportsSql);
    let pushed = 0;
    for (const r of unsynced) {
      const res = await fetch(`${worker_url}/api/reports`, {
        method: "POST",
        headers: { ...auth, "Content-Type": "application/json" },
        body: JSON.stringify(r),
      });
      if (!res.ok) break; // fail-soft: rows stay synced=0, retried next startup
      await db.execute(markReportSyncedSql, [r.id]);
      pushed++;
    }

    const cursorRows = await db.select<{ c: string | null }[]>(maxReportGeneratedAtSql);
    const cursor = cursorRows[0]?.c ?? EPOCH;
    const res = await fetch(
      `${worker_url}/api/reports?since=${encodeURIComponent(cursor)}`,
      { headers: auth }
    );
    if (!res.ok) return { pushed, pulled: 0 };
    const body = (await res.json()) as { reports: ReportRow[] };
    let pulled = 0;
    for (const r of body.reports ?? []) {
      const result = await db.execute(insertReportSql, [
        r.id, r.style, r.period_type, r.start_date, r.end_date,
        r.provider, r.model, r.generated_at, r.revision_count, r.report_text, 1,
      ]);
      pulled += result.rowsAffected;
    }
    return { pushed, pulled };
  } catch (e) {
    console.error("syncReports failed:", e);
    return { offline: true };
  }
}

/**
 * Delete a report from D1 first, then locally.
 *
 * That order is the whole correctness argument: the pull above uses
 * MAX(generated_at) as its cursor, so a local-only delete of the newest report
 * lowers the cursor and the next startup pulls it back from D1. Deliberately
 * not fail-soft — no tombstone table means an offline delete cannot be replayed
 * later, so it is refused instead. The caller shows the error.
 */
export async function deleteReport(id: string): Promise<void> {
  const { worker_url, worker_auth_token } = await getConfig();
  if (!worker_url) throw new Error("Cloud sync is not set up — cannot delete.");
  const res = await fetch(`${worker_url}/api/reports?id=${encodeURIComponent(id)}`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${worker_auth_token}` },
  });
  if (!res.ok) throw new Error(`Worker refused the delete (${res.status})`);
  await deleteReportLocal(id);
}
