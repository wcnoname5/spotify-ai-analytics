export interface Env {
  DB: D1Database;
  AUTH_TOKEN: string;
}

interface TokenRow {
  user_id: string;
  access_token: string;
  refresh_token: string;
  expires_at: string;
  scopes?: string | null;
}

const CURSOR_KEY = "last_played_at_ms";

function badRequest(message: string): Response {
  return new Response(message, { status: 400 });
}

function notFound(message: string): Response {
  return Response.json({ error: message }, { status: 404 });
}

function isTokenRow(value: unknown): value is TokenRow {
  if (typeof value !== "object" || value === null) return false;
  const row = value as Record<string, unknown>;
  return (
    typeof row.access_token === "string" &&
    typeof row.refresh_token === "string" &&
    typeof row.expires_at === "string"
  );
}

/** GET /api/tokens?user_id= -> the token row as JSON; 404 if missing */
export async function handleGetTokens(
  request: Request,
  env: Env
): Promise<Response> {
  const url = new URL(request.url);
  const userId = url.searchParams.get("user_id");
  if (!userId) return badRequest("Missing 'user_id' query param");

  const row = await env.DB.prepare(
    "SELECT user_id, access_token, refresh_token, expires_at, scopes FROM spotify_tokens WHERE user_id = ?"
  )
    .bind(userId)
    .first<TokenRow>();

  if (!row) return notFound(`No token row for user_id '${userId}'`);
  return Response.json(row);
}

/** POST /api/tokens?user_id= body { access_token, refresh_token, expires_at, scopes? } -> upsert */
export async function handlePostTokens(
  request: Request,
  env: Env
): Promise<Response> {
  const url = new URL(request.url);
  const userId = url.searchParams.get("user_id");
  if (!userId) return badRequest("Missing 'user_id' query param");

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return badRequest("Malformed JSON body");
  }

  if (!isTokenRow(body)) {
    return badRequest(
      "Body must include access_token, refresh_token, expires_at"
    );
  }

  await env.DB.prepare(
    `INSERT INTO spotify_tokens (user_id, access_token, refresh_token, expires_at, scopes)
     VALUES (?, ?, ?, ?, ?)
     ON CONFLICT(user_id) DO UPDATE SET
       access_token = excluded.access_token,
       refresh_token = excluded.refresh_token,
       expires_at = excluded.expires_at,
       scopes = excluded.scopes`
  )
    .bind(
      userId,
      body.access_token,
      body.refresh_token,
      body.expires_at,
      body.scopes ?? null
    )
    .run();

  return Response.json({ ok: true });
}

/** GET /api/cursor -> { last_played_at_ms: n }, defaults to 0 */
export async function handleGetCursor(
  _request: Request,
  env: Env
): Promise<Response> {
  const row = await env.DB.prepare(
    "SELECT value FROM sync_state WHERE key = ?"
  )
    .bind(CURSOR_KEY)
    .first<{ value: number }>();

  return Response.json({ last_played_at_ms: row?.value ?? 0 });
}

/** POST /api/cursor body { last_played_at_ms: n } -> upsert */
export async function handlePostCursor(
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
    typeof (body as { last_played_at_ms?: unknown }).last_played_at_ms !==
      "number" ||
    !Number.isFinite((body as { last_played_at_ms: number }).last_played_at_ms)
  ) {
    return badRequest("Body must be { last_played_at_ms: <number> }");
  }

  const value = (body as { last_played_at_ms: number }).last_played_at_ms;

  await env.DB.prepare(
    `INSERT INTO sync_state (key, value) VALUES (?, ?)
     ON CONFLICT(key) DO UPDATE SET value = excluded.value`
  )
    .bind(CURSOR_KEY, value)
    .run();

  return Response.json({ ok: true });
}
