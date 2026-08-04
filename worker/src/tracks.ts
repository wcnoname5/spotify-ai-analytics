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

export const INSERT_SQL = `INSERT OR IGNORE INTO listening_history (${COLUMNS.join(
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

/**
 * Rows per page.
 *
 * This used to be unbounded. A user who imported a full Spotify export has
 * ~100k rows in D1, and `.all()` materialises the whole result set in Worker
 * memory (128 MB) before serialising it — so the first sync on a new machine
 * either OOMed the Worker or took minutes. 5000 rows is a few MB of JSON.
 */
const PAGE_SIZE = 5000;

/**
 * GET /api/tracks?since=<iso>[&since_id=<id>] or ?from=<iso>&to=<iso>
 *   -> { tracks: [...], next_since?: <iso>, next_id?: <id> }
 *
 * When `next_since` comes back there may be more; pass both cursor values to the
 * next call. A short page is definitively the end, so no cursor goes back and
 * the caller stops.
 *
 * The cursor is `(played_at, id)`, not `played_at` alone. Two plays can share a
 * timestamp — the same second from two devices in a data export — and with a
 * bare `played_at > cursor` any tie straddling a page boundary is skipped
 * forever, because the next sync starts from the same cursor. `id` is the
 * primary key, so the pair is unique and the resume point is exact.
 *
 * Without `since_id` the comparison is `>=`, not `>`: the first call of a sync
 * uses the local `MAX(played_at)`, and a row in D1 tying with it would otherwise
 * never be fetched. The overlap re-sends one boundary row, which INSERT OR
 * IGNORE drops.
 */
export async function handleGetTracks(
  request: Request,
  env: Env
): Promise<Response> {
  const url = new URL(request.url);
  const since = url.searchParams.get("since");
  const sinceId = url.searchParams.get("since_id");
  const from = url.searchParams.get("from");
  const to = url.searchParams.get("to");

  let statement;
  if (since !== null) {
    if (!ISO_RE.test(since)) return badRequest("Invalid 'since' (ISO-8601 expected)");
    statement =
      sinceId !== null
        ? env.DB.prepare(
            "SELECT * FROM listening_history " +
              "WHERE played_at > ? OR (played_at = ? AND id > ?) " +
              "ORDER BY played_at ASC, id ASC LIMIT ?"
          ).bind(since, since, sinceId, PAGE_SIZE)
        : env.DB.prepare(
            "SELECT * FROM listening_history WHERE played_at >= ? " +
              "ORDER BY played_at ASC, id ASC LIMIT ?"
          ).bind(since, PAGE_SIZE);
  } else if (from !== null && to !== null) {
    if (!ISO_RE.test(from) || !ISO_RE.test(to)) {
      return badRequest("Invalid 'from'/'to' (ISO-8601 expected)");
    }
    statement = env.DB.prepare(
      "SELECT * FROM listening_history WHERE played_at >= ? AND played_at <= ? " +
        "ORDER BY played_at ASC, id ASC LIMIT ?"
    ).bind(from, to, PAGE_SIZE);
  } else {
    return badRequest("Provide 'since' or 'from'/'to' query params");
  }

  const { results } = await statement.all<{ played_at: string; id: string }>();
  const last = results.length === PAGE_SIZE ? results[results.length - 1] : undefined;

  return Response.json({
    tracks: results,
    next_since: last?.played_at,
    next_id: last?.id,
  });
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
