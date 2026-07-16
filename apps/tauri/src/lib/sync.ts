// Startup incremental sync: pull new plays from the Worker (D1) into the
// local SQLite cache. Local SQLite is a pull-only mirror — the only writes it
// ever gets are these INSERT OR IGNORE rows sourced from D1 via the Worker.
import maxPlayedAtSql from "@sql/max_played_at.sql?raw";
import insertTrackSql from "@sql/insert_track.sql?raw";
// Rust-side fetch: the Worker has no CORS headers (frozen by design), and the
// webview's own fetch enforces CORS against the localhost origin.
import { fetch } from "@tauri-apps/plugin-http";
import { getDb } from "./db";
import type { TrackRow } from "./api";

const EPOCH = "1970-01-01T00:00:00Z";

export type SyncResult =
  | { inserted: number }
  | { offline: true; reason: "unconfigured" | "error" };

export async function syncOnStartup(): Promise<SyncResult> {
  if (!__WORKER_URL__) return { offline: true, reason: "unconfigured" };

  try {
    const db = await getDb();
    const cursorRows = await db.select<{ c: string | null }[]>(maxPlayedAtSql);
    const cursor = cursorRows[0]?.c ?? EPOCH;

    const res = await fetch(`${__WORKER_URL__}/api/tracks?since=${encodeURIComponent(cursor)}`, {
      headers: { Authorization: `Bearer ${__WORKER_AUTH_TOKEN__}` },
    });
    if (!res.ok) {
      console.error(`syncOnStartup: worker responded ${res.status}`);
      return { offline: true, reason: "error" };
    }

    const body = (await res.json()) as { tracks: TrackRow[] };
    const tracks = body.tracks ?? [];

    // No explicit BEGIN/COMMIT here: tauri-plugin-sql's Database is backed by
    // an sqlx connection pool, so a transaction started on one connection can
    // have its COMMIT routed to another once anything else queries
    // concurrently — the COMMIT then errors and leaves a pooled connection
    // stuck mid-transaction. The inserts are `INSERT OR IGNORE` and
    // idempotent, so running them sequentially without a wrapping
    // transaction is safe: a partial sync is harmless and the next startup
    // re-pulls from the same cursor.
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
