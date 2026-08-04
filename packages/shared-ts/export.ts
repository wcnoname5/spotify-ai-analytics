// Parsing the Spotify "extended streaming history" data export.
//
// The export is a folder of `Streaming_History_Audio_*.json`, each an array of
// records with different field names from the Web API's recently-played
// response — `ts` not `played_at`, `spotify_track_uri` not `track.uri`. This
// replaced the Polars + Pydantic path in `packages/dataloader`, which pulled in
// 156 MB of dependencies to read JSON.
//
// The row id comes from shared-ts/rowid, so a play that appears in both the
// export and the API collides on INSERT OR IGNORE rather than being counted
// twice. That is the whole reason this parser is not local to the importer.

import { playRowId, playedAtIso } from "./rowid";

/** One record as it appears in the export. Every field is treated as untrusted:
 *  the export includes podcast and audiobook rows with null track metadata. */
export interface ExportRecord {
  ts?: string;
  ms_played?: number;
  platform?: string | null;
  conn_country?: string | null;
  master_metadata_track_name?: string | null;
  master_metadata_album_artist_name?: string | null;
  master_metadata_album_album_name?: string | null;
  spotify_track_uri?: string | null;
  reason_start?: string | null;
  reason_end?: string | null;
  shuffle?: boolean | null;
  skipped?: boolean | null;
}

/** A row shaped for `POST /api/tracks`. Matches worker/src/tracks.ts's TrackRow. */
export interface TrackRow {
  id: string;
  track_id: string;
  track_name: string | null;
  artist_name: string | null;
  album_name: string | null;
  played_at: string;
  ms_played: number | null;
  source: "json_import";
  platform: string | null;
  conn_country: string | null;
  reason_start: string | null;
  reason_end: string | null;
  shuffle: number | null;
  skipped: number | null;
}

/** SQLite has no boolean type; the column is INTEGER, as Python's int() gave. */
const bit = (v: boolean | null | undefined): number | null =>
  v === null || v === undefined ? null : v ? 1 : 0;

/**
 * Convert one export record, or null when it cannot be a listening_history row.
 *
 * Skipped: podcast and audiobook plays (no `spotify_track_uri`) and unparseable
 * timestamps. Both are normal contents of a real export, not corruption — an
 * importer that threw on them would fail on almost every real user's data.
 */
export async function toTrackRow(record: ExportRecord): Promise<TrackRow | null> {
  const trackUri = record.spotify_track_uri;
  if (!trackUri) return null;

  const playedAtMs = Date.parse(record.ts ?? "");
  if (Number.isNaN(playedAtMs)) return null;
  const played_at = playedAtIso(playedAtMs);

  return {
    id: await playRowId(trackUri, played_at),
    track_id: trackUri,
    track_name: record.master_metadata_track_name ?? null,
    artist_name: record.master_metadata_album_artist_name ?? null,
    album_name: record.master_metadata_album_album_name ?? null,
    played_at,
    ms_played: record.ms_played ?? null,
    source: "json_import",
    platform: record.platform ?? null,
    conn_country: record.conn_country ?? null,
    reason_start: record.reason_start ?? null,
    reason_end: record.reason_end ?? null,
    shuffle: bit(record.shuffle),
    skipped: bit(record.skipped),
  };
}

export interface ParsedFile {
  rows: TrackRow[];
  skipped: number;
}

/**
 * Parse one export file's JSON text.
 *
 * Throws only when the text is not a JSON array — that means the wrong file was
 * picked, which is worth telling the user about. Individual unusable records are
 * counted in `skipped`, not raised.
 */
export async function parseExportFile(text: string): Promise<ParsedFile> {
  const parsed: unknown = JSON.parse(text);
  if (!Array.isArray(parsed)) {
    throw new Error("expected a JSON array of listening records");
  }

  const rows: TrackRow[] = [];
  let skipped = 0;
  for (const record of parsed) {
    const row = await toTrackRow(record as ExportRecord);
    if (row) rows.push(row);
    else skipped++;
  }
  return { rows, skipped };
}
