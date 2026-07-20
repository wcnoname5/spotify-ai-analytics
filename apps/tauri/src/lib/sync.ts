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
import type { TrackRow } from "./api";

const EPOCH = "1970-01-01T00:00:00Z";

export type SyncResult =
  | { inserted: number }
  | { offline: true; reason: "unconfigured" | "error" };

export async function syncOnStartup(): Promise<SyncResult> {
  const { worker_url, worker_auth_token } = await getConfig();
  if (!worker_url) return { offline: true, reason: "unconfigured" };

  try {
    const db = await getDb();
    const cursorRows = await db.select<{ c: string | null }[]>(maxPlayedAtSql);
    const cursor = cursorRows[0]?.c ?? EPOCH;

    const res = await fetch(`${worker_url}/api/tracks?since=${encodeURIComponent(cursor)}`, {
      headers: { Authorization: `Bearer ${worker_auth_token}` },
    });
    if (!res.ok) {
      console.error(`syncOnStartup: worker responded ${res.status}`);
      return { offline: true, reason: "error" };
    }

    const body = (await res.json()) as { tracks: TrackRow[] };
    const tracks = body.tracks ?? [];

    // No BEGIN/COMMIT: sqlx pooling can route COMMIT to a different connection.
    // INSERT OR IGNORE is idempotent; a partial sync re-pulls from the same cursor.
    let inserted = 0;
    for (const t of tracks) {
      const result = await db.execute(insertTrackSql, [
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
        t.skipped ?? null,
      ]);
      inserted += result.rowsAffected;
    }

    return { inserted };
  } catch (e) {
    console.error("syncOnStartup failed:", e);
    return { offline: true, reason: "error" };
  }
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
