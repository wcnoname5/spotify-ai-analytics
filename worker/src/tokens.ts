import type { Env } from "./index";

interface TokenRow {
  user_id: string;
  access_token: string;
  refresh_token: string;
  expires_at: string;
  scopes?: string | null;
}

/** Upsert one encrypted token row. Bound as (user_id, access, refresh, expires_at, scopes). */
export const UPSERT_TOKEN_SQL = `INSERT INTO spotify_tokens (user_id, access_token, refresh_token, expires_at, scopes)
     VALUES (?, ?, ?, ?, ?)
     ON CONFLICT(user_id) DO UPDATE SET
       access_token = excluded.access_token,
       refresh_token = excluded.refresh_token,
       expires_at = excluded.expires_at,
       scopes = excluded.scopes`;

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

  await env.DB.prepare(UPSERT_TOKEN_SQL)
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
