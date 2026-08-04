// Authorization Code with PKCE, the flow Spotify requires (Implicit Grant was
// removed in Nov 2025). WebCrypto only — this has to run in a WebView.
//
// Redirect URI is always http://127.0.0.1:<port>/callback, never `localhost`:
// Spotify stopped accepting `localhost` in Nov 2025.

const AUTHORIZE_URL = "https://accounts.spotify.com/authorize";
const TOKEN_URL = "https://accounts.spotify.com/api/token";

/** The loopback port the Rust side listens on; must match the redirect URI
 *  registered in the user's Spotify app. */
export const CALLBACK_PORT = 8888;

export const redirectUri = (port: number = CALLBACK_PORT) =>
  `http://127.0.0.1:${port}/callback`;

/** Scopes the app actually uses: recently-played for sync, the rest for the
 *  MCP playback tools. Asking for more than this would be asking the user to
 *  approve capabilities that do not exist. */
export const SCOPES = [
  "user-read-recently-played",
  "user-read-playback-state",
  "user-modify-playback-state",
  "user-read-currently-playing",
].join(" ");

/** base64url without padding — what RFC 7636 specifies for both values. */
function b64urlNoPad(bytes: Uint8Array): string {
  let raw = "";
  for (const b of bytes) raw += String.fromCharCode(b);
  return btoa(raw).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/** A high-entropy code verifier: 32 random bytes, base64url — 43 chars, the
 *  RFC's minimum length. */
export function createVerifier(): string {
  return b64urlNoPad(crypto.getRandomValues(new Uint8Array(32)));
}

/** S256 challenge: base64url(SHA-256(ASCII(verifier))). */
export async function challengeFor(verifier: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier));
  return b64urlNoPad(new Uint8Array(digest));
}

/** Opaque CSRF value echoed back in the callback; compare before exchanging. */
export function createState(): string {
  return b64urlNoPad(crypto.getRandomValues(new Uint8Array(16)));
}

export interface AuthRequest {
  url: string;
  verifier: string;
  state: string;
}

/** Build the authorize URL plus the two values the callback has to be checked against. */
export async function buildAuthRequest(
  clientId: string,
  port: number = CALLBACK_PORT
): Promise<AuthRequest> {
  const verifier = createVerifier();
  const state = createState();
  const params = new URLSearchParams({
    client_id: clientId,
    response_type: "code",
    redirect_uri: redirectUri(port),
    scope: SCOPES,
    code_challenge_method: "S256",
    code_challenge: await challengeFor(verifier),
    state,
  });
  return { url: `${AUTHORIZE_URL}?${params}`, verifier, state };
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  expires_in: number;
  scope?: string;
}

/**
 * Exchange the authorization code for tokens.
 *
 * `fetchImpl` is injected because the WebView's own fetch is CORS-bound and
 * accounts.spotify.com sends no CORS headers — the caller passes Tauri's
 * plugin-http fetch, which goes through Rust. Same reason `lib/sync.ts` does it.
 */
export async function exchangeCode(
  clientId: string,
  code: string,
  verifier: string,
  fetchImpl: typeof fetch,
  port: number = CALLBACK_PORT
): Promise<TokenResponse> {
  const resp = await fetchImpl(TOKEN_URL, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "authorization_code",
      code,
      redirect_uri: redirectUri(port),
      client_id: clientId,
      code_verifier: verifier,
    }),
  });
  if (!resp.ok) {
    // Spotify puts the actionable part in the body ("invalid_grant",
    // "redirect_uri mismatch"); the status alone tells the user nothing.
    throw new Error(`Token exchange failed: HTTP ${resp.status} ${await resp.text()}`);
  }
  const tok = (await resp.json()) as TokenResponse;
  if (!tok.refresh_token) {
    // Without this the hourly cron has nothing to refresh with and every later
    // sync fails — better to fail here, where the user can just retry.
    throw new Error("Spotify returned no refresh_token");
  }
  return tok;
}

/** `expires_at` in the format the D1 `spotify_tokens` row uses (ISO 8601, UTC). */
export function expiresAt(expiresIn: number, now: number = Date.now()): string {
  return new Date(now + expiresIn * 1000).toISOString();
}
