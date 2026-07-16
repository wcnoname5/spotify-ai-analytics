// Startup incremental sync: pull new plays from the Worker (D1) into the
// local SQLite cache. Local SQLite is a pull-only mirror — the only writes it
// ever gets are these INSERT OR IGNORE rows sourced from D1 via the Worker.
import maxPlayedAtSql from "@sql/max_played_at.sql?raw";
import insertTrackSql from "@sql/insert_track.sql?raw";
import { getDb } from "./db";
import type { TrackRow } from "./api";

const EPOCH = "1970-01-01T00:00:00Z";

export type SyncResult = { inserted: number } | { offline: true };

export async function syncOnStartup(): Promise<SyncResult> {
  if (!__WORKER_URL__) return { offline: true };

  try {
    const db = await getDb();
    const cursorRows = await db.select<{ c: string | null }[]>(maxPlayedAtSql);
    const cursor = cursorRows[0]?.c ?? EPOCH;

    const res = await fetch(`${__WORKER_URL__}/api/tracks?since=${encodeURIComponent(cursor)}`, {
      headers: { Authorization: `Bearer ${__WORKER_AUTH_TOKEN__}` },
    });
    if (!res.ok) return { offline: true };

    const body = (await res.json()) as { tracks: TrackRow[] };
    const tracks = body.tracks ?? [];

    let inserted = 0;
    await db.execute("BEGIN");
    try {
      for (const t of tracks) {
        // TrackRow (api.ts) mirrors only the API payload fields; the export-only
        // columns (platform, conn_country, ...) aren't part of that shape and
        // always bind null here.
        const result = await db.execute(insertTrackSql, [
          t.id,
          t.track_id,
          t.track_name ?? null,
          t.artist_name ?? null,
          t.album_name ?? null,
          t.played_at,
          t.ms_played ?? null,
          t.source ?? null,
          null, // platform
          null, // conn_country
          null, // reason_start
          null, // reason_end
          null, // shuffle
          null, // skipped
        ]);
        inserted += result.rowsAffected;
      }
      await db.execute("COMMIT");
    } catch (err) {
      await db.execute("ROLLBACK");
      throw err;
    }

    return { inserted };
  } catch {
    return { offline: true };
  }
}
