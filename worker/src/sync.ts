// Hourly cron sync: Spotify recently-played -> D1.
// Shared with the desktop frontend: the app encrypts tokens with the same code
// this cron decrypts them with. See packages/shared-ts/README.md.
import { fernetDecrypt, fernetEncrypt } from "../../packages/shared-ts/fernet";
import { INSERT_SQL } from "./tracks";

export interface SyncEnv {
  DB: D1Database;
  SPOTIFY_CLIENT_ID: string;
  TOKEN_ENCRYPT_KEY: string;
  SPOTIFY_USER_ID?: string;
}

const TOKEN_URL = "https://accounts.spotify.com/api/token";
const RECENTLY_PLAYED_URL = "https://api.spotify.com/v1/me/player/recently-played";
const CURSOR_KEY = "last_played_at_ms";

interface RefreshResponse {
  access_token: string;
  refresh_token?: string;
  expires_in: number;
  scope?: string;
}

/** Python's token_store accepts isoformat (tz-aware, "+00:00" or "Z") or legacy naive "YYYY-MM-DD HH:MM:SS" (UTC). */
function parseExpiresAt(raw: string): number {
  let s = raw.includes("T") ? raw : raw.replace(" ", "T");
  s = s.replace(/(\.\d{3})\d+/, "$1"); // Python microseconds -> ms for Date.parse
  if (!/Z$|[+-]\d{2}:\d{2}$/.test(s)) s += "Z";
  return Date.parse(s);
}

/** Refresh the access token and write the re-encrypted row back to D1 BEFORE
 * anything else runs — Spotify rotates refresh tokens on use, and losing the
 * new one strands every later cron run in invalid_grant. */
async function refreshAndStore(
  env: SyncEnv,
  userId: string,
  refreshToken: string
): Promise<{ accessToken: string; refreshToken: string }> {
  const resp = await fetch(TOKEN_URL, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "refresh_token",
      refresh_token: refreshToken,
      client_id: env.SPOTIFY_CLIENT_ID,
    }),
  });
  if (!resp.ok) throw new Error(`Token refresh failed: HTTP ${resp.status}`);
  const tok = (await resp.json()) as RefreshResponse;
  const newRefresh = tok.refresh_token ?? refreshToken;
  const expiresAt = new Date(Date.now() + tok.expires_in * 1000).toISOString();
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
      await fernetEncrypt(tok.access_token, env.TOKEN_ENCRYPT_KEY),
      await fernetEncrypt(newRefresh, env.TOKEN_ENCRYPT_KEY),
      expiresAt,
      tok.scope ?? ""
    )
    .run();
  return { accessToken: tok.access_token, refreshToken: newRefresh };
}

async function sha1Hex(s: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-1", new TextEncoder().encode(s));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

interface ParsedRow {
  id: string;
  trackId: string;
  trackName: string | null;
  artistName: string | null;
  albumName: string | null;
  playedAtIso: string;
  msPlayed: number | null;
  playedAtMs: number;
}

/** Port of pipeline.parse_api_item — identical row id (sha1 of "uri:iso") so
 * inserts stay idempotent across the Python and Worker sync paths. */
async function parseApiItem(item: Record<string, any>): Promise<ParsedRow | null> {
  const track = item.track ?? {};
  const trackUri: string = track.uri ?? "";
  const playedAtMs = Date.parse(item.played_at ?? "");
  if (Number.isNaN(playedAtMs)) return null;
  // Seconds-precision UTC ISO, matching Python's strftime("%Y-%m-%dT%H:%M:%SZ")
  const playedAtIso = new Date(playedAtMs).toISOString().replace(/\.\d{3}Z$/, "Z");
  return {
    id: await sha1Hex(`${trackUri}:${playedAtIso}`),
    trackId: trackUri,
    trackName: track.name ?? null,
    artistName: track.artists?.[0]?.name ?? null,
    albumName: track.album?.name ?? null,
    playedAtIso,
    msPlayed: track.duration_ms ?? null,
    playedAtMs,
  };
}

export interface SyncResult {
  inserted: number;
  skippedParseError: number;
  cursorMs: number;
}

export async function runSync(env: SyncEnv): Promise<SyncResult> {
  const userId = env.SPOTIFY_USER_ID ?? "default";
  const row = await env.DB.prepare(
    "SELECT access_token, refresh_token, expires_at FROM spotify_tokens WHERE user_id = ?"
  )
    .bind(userId)
    .first<{ access_token: string; refresh_token: string; expires_at: string }>();
  if (!row) throw new Error(`No token row for user '${userId}' — run spotify-mcp reauth + spotify-mcp cloud seed`);

  let accessToken = await fernetDecrypt(row.access_token, env.TOKEN_ENCRYPT_KEY);
  let refreshToken = await fernetDecrypt(row.refresh_token, env.TOKEN_ENCRYPT_KEY);
  if (parseExpiresAt(row.expires_at) <= Date.now()) {
    ({ accessToken, refreshToken } = await refreshAndStore(env, userId, refreshToken));
  }

  const cursorRow = await env.DB.prepare("SELECT value FROM sync_state WHERE key = ?")
    .bind(CURSOR_KEY)
    .first<{ value: number }>();
  const cursorMs = cursorRow?.value ?? 0;

  const url = new URL(RECENTLY_PLAYED_URL);
  url.searchParams.set("limit", "50");
  if (cursorMs > 0) url.searchParams.set("after", String(cursorMs));

  let resp = await fetch(url, { headers: { Authorization: `Bearer ${accessToken}` } });
  if (resp.status === 401) {
    ({ accessToken, refreshToken } = await refreshAndStore(env, userId, refreshToken));
    resp = await fetch(url, { headers: { Authorization: `Bearer ${accessToken}` } });
  }
  if (!resp.ok) throw new Error(`recently-played failed: HTTP ${resp.status}`);
  const data = (await resp.json()) as { items?: Record<string, any>[] };

  const rows: ParsedRow[] = [];
  let skippedParseError = 0;
  let newCursorMs = cursorMs;
  for (const item of data.items ?? []) {
    const parsed = await parseApiItem(item);
    if (parsed === null) {
      skippedParseError++;
      continue;
    }
    newCursorMs = Math.max(newCursorMs, parsed.playedAtMs);
    rows.push(parsed);
  }

  let inserted = 0;
  if (rows.length > 0) {
    const results = await env.DB.batch(
      rows.map((r) =>
        env.DB.prepare(INSERT_SQL).bind(
          r.id, r.trackId, r.trackName, r.artistName, r.albumName,
          r.playedAtIso, r.msPlayed, "api",
          null, null, null, null, null, null
        )
      )
    );
    inserted = results.reduce((sum, r) => sum + (r.meta.changes ?? 0), 0);
  }

  if (newCursorMs > cursorMs) {
    await env.DB.prepare(
      "INSERT INTO sync_state (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value"
    )
      .bind(CURSOR_KEY, newCursorMs)
      .run();
  }

  return { inserted, skippedParseError, cursorMs: newCursorMs };
}
