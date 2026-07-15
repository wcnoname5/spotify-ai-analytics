export interface Env {
  DB: D1Database;
  AUTH_TOKEN: string;
}

interface TrackRow {
  id: string;
  track_id: string;
  track_name?: string | null;
  artist_name?: string | null;
  album_name?: string | null;
  played_at: string;
  ms_played?: number | null;
  source?: string | null;
  platform?: string | null;
  conn_country?: string | null;
  reason_start?: string | null;
  reason_end?: string | null;
  shuffle?: number | null;
  skipped?: number | null;
}

const COLUMNS = [
  "id",
  "track_id",
  "track_name",
  "artist_name",
  "album_name",
  "played_at",
  "ms_played",
  "source",
  "platform",
  "conn_country",
  "reason_start",
  "reason_end",
  "shuffle",
  "skipped",
] as const;

const INSERT_SQL = `INSERT OR IGNORE INTO listening_history (${COLUMNS.join(
  ", "
)}) VALUES (${COLUMNS.map(() => "?").join(", ")})`;

function badRequest(message: string): Response {
  return new Response(message, { status: 400 });
}

function isTrackRow(value: unknown): value is TrackRow {
  if (typeof value !== "object" || value === null) return false;
  const row = value as Record<string, unknown>;
  return (
    typeof row.id === "string" &&
    typeof row.track_id === "string" &&
    typeof row.played_at === "string"
  );
}

// comparing 'played_at' (ISO-8601 TEXT column)
const ISO_RE = /^\d{4}-\d{2}-\d{2}T/;

/** GET /api/tracks?since=<iso> or ?from=<iso>&to=<iso> -> { tracks: [...] } */
export async function handleGetTracks(
  request: Request,
  env: Env
): Promise<Response> {
  const url = new URL(request.url);
  const since = url.searchParams.get("since");
  const from = url.searchParams.get("from");
  const to = url.searchParams.get("to");

  let statement;
  if (since !== null) {
    if (!ISO_RE.test(since)) return badRequest("Invalid 'since' (ISO-8601 expected)");
    statement = env.DB.prepare(
      "SELECT * FROM listening_history WHERE played_at > ? ORDER BY played_at ASC"
    ).bind(since);
  } else if (from !== null && to !== null) {
    if (!ISO_RE.test(from) || !ISO_RE.test(to)) {
      return badRequest("Invalid 'from'/'to' (ISO-8601 expected)");
    }
    statement = env.DB.prepare(
      "SELECT * FROM listening_history WHERE played_at >= ? AND played_at <= ? ORDER BY played_at ASC"
    ).bind(from, to);
  } else {
    return badRequest("Provide 'since' or 'from'/'to' query params");
  }

  const { results } = await statement.all();
  return Response.json({ tracks: results });
}

/** POST /api/tracks body { tracks: [row, ...] } -> { inserted: n } */
export async function handlePostTracks(
  request: Request,
  env: Env
): Promise<Response> {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return badRequest("Malformed JSON body");
  }

  if (
    typeof body !== "object" ||
    body === null ||
    !Array.isArray((body as { tracks?: unknown }).tracks)
  ) {
    return badRequest("Body must be { tracks: [...] }");
  }

  const tracks = (body as { tracks: unknown[] }).tracks;
  if (!tracks.every(isTrackRow)) {
    return badRequest("Each track requires id, track_id, played_at");
  }

  if (tracks.length === 0) {
    return Response.json({ inserted: 0 });
  }

  const statements = tracks.map((track) =>
    env.DB.prepare(INSERT_SQL).bind(
      track.id,
      track.track_id,
      track.track_name ?? null,
      track.artist_name ?? null,
      track.album_name ?? null,
      track.played_at,
      track.ms_played ?? null,
      track.source ?? "api",
      track.platform ?? null,
      track.conn_country ?? null,
      track.reason_start ?? null,
      track.reason_end ?? null,
      track.shuffle ?? null,
      track.skipped ?? null
    )
  );

  const results = await env.DB.batch(statements);
  const inserted = results.reduce((sum, r) => sum + (r.meta.changes ?? 0), 0);
  return Response.json({ inserted });
}

/** GET /api/tracks/count -> { count: n } */
export async function handleGetTracksCount(
  _request: Request,
  env: Env
): Promise<Response> {
  const row = await env.DB.prepare(
    "SELECT COUNT(*) AS count FROM listening_history"
  ).first<{ count: number }>();
  return Response.json({ count: row?.count ?? 0 });
}
