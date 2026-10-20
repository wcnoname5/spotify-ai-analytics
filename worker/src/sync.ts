// Hourly cron sync: Spotify recently-played -> D1.
// Shared with the desktop frontend: the app encrypts tokens with the same code
// this cron decrypts them with. See packages/shared-ts/README.md.
import { fernetDecrypt, fernetEncrypt } from "../../packages/shared-ts/fernet";
import { playRowId, playedAtIso } from "../../packages/shared-ts/rowid";
import type { Env } from "./index";
import { UPSERT_TOKEN_SQL } from "./tokens";
import { INSERT_SQL } from "./tracks";

const TOKEN_URL = "https://accounts.spotify.com/api/token";
const RECENTLY_PLAYED_URL = "https://api.spotify.com/v1/me/player/recently-played";
const CURSOR_KEY = "last_played_at_ms";

interface RefreshResponse {
  access_token: string;
  refresh_token?: string;
  expires_in: number;
  scope?: string;
}

/** New rows are `toISOString()`; older rows may be naive "YYYY-MM-DD HH:MM:SS" (UTC) or carry microseconds. */
function parseExpiresAt(raw: string): number {
  let s = raw.includes("T") ? raw : raw.replace(" ", "T");
  s = s.replace(/(\.\d{3})\d+/, "$1"); // microseconds -> ms for Date.parse
  if (!/Z$|[+-]\d{2}:\d{2}$/.test(s)) s += "Z";
  return Date.parse(s);
}

/** Refresh the access token and write the re-encrypted row back to D1 BEFORE
 * anything else runs — Spotify rotates refresh tokens on use, and losing the
 * new one strands every later cron run in invalid_grant. */
async function refreshAndStore(
  env: Env,
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
  await env.DB.prepare(UPSERT_TOKEN_SQL)
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

/** One recently-played item -> a listening_history row. The row id comes from shared-ts/rowid so a
 * play imported from the data export and the same play seen by this cron collide
 * on INSERT OR IGNORE instead of being counted twice. */
async function parseApiItem(item: Record<string, any>): Promise<ParsedRow | null> {
  const track = item.track ?? {};
  const trackUri: string = track.uri ?? "";
  const playedAtMs = Date.parse(item.played_at ?? "");
  if (Number.isNaN(playedAtMs)) return null;
  const iso = playedAtIso(playedAtMs);
  return {
    id: await playRowId(trackUri, iso),
    trackId: trackUri,
    trackName: track.name ?? null,
    artistName: track.artists?.[0]?.name ?? null,
    albumName: track.album?.name ?? null,
    playedAtIso: iso,
    msPlayed: track.duration_ms ?? null,
    playedAtMs,
  };
}

export interface SyncResult {
  inserted: number;
  skippedParseError: number;
  cursorMs: number;
}

export async function runSync(env: Env): Promise<SyncResult> {
  // One deployment serves one Spotify account, and the deploy runs before OAuth
  // learns its id — so take the newest row rather than a configured user id.
  const row = await env.DB.prepare(
    "SELECT user_id, access_token, refresh_token, expires_at FROM spotify_tokens ORDER BY rowid DESC LIMIT 1"
  ).first<{ user_id: string; access_token: string; refresh_token: string; expires_at: string }>();
  if (!row) throw new Error("No Spotify tokens in D1 — run Setup → Authorize Spotify");
  const userId = row.user_id;

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
