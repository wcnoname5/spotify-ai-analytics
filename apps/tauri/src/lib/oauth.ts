// Spotify authorization, end to end, from the desktop app.
//
// This replaced `spotify-mcp reauth` (a spawned Python process running
// `wizard/oauth_step.py`). The parts are split by what each layer can do:
//
//   Rust   — listens on 127.0.0.1:8888 and opens the browser (src-tauri/src/oauth.rs)
//   shared — builds the authorize URL, exchanges the code, encrypts the tokens
//            (packages/shared-ts/{pkce,fernet}.ts, shared with the Worker)
//   here   — sequences them and posts the result to the Worker
//
// The tokens go straight to D1 and are never stored locally. The hourly Worker
// cron is what uses them, and it reads them from D1; a local tokens.db would be
// a second copy of a credential with no reader.
import { fetch } from "@tauri-apps/plugin-http";
import { invoke } from "@tauri-apps/api/core";
import { fernetEncrypt } from "@shared/fernet";
import { CALLBACK_PORT, buildAuthRequest, exchangeCode, expiresAt } from "@shared/pkce";

import { getConfig } from "./config";

/** Human-readable failure. Every throw here is something the user can act on. */
class AuthError extends Error {}

/**
 * Run the whole flow: browser → callback → exchange → encrypt → Worker.
 *
 * Resolves with the Spotify user id the tokens belong to.
 */
export async function authorizeSpotify(): Promise<{ userId: string }> {
  const cfg = await getConfig();
  if (!cfg.configured.client_id) {
    throw new AuthError("Enter your Spotify Client ID first.");
  }
  if (!cfg.configured.worker) {
    // Without somewhere to put them, a successful authorization would be
    // discarded — better to say so before sending the user to the browser.
    throw new AuthError(
      "Set up Cloud sync first: the tokens are stored in your Cloudflare D1, not on this machine."
    );
  }

  const clientId = cfg.spotify_client_id;
  const request = await buildAuthRequest(clientId, CALLBACK_PORT);

  // Rust binds the port before opening the browser, so the redirect cannot
  // arrive at a closed socket. Resolves with the callback's query string.
  const query = new URLSearchParams(
    await invoke<string>("await_oauth_callback", {
      authorizeUrl: request.url,
      port: CALLBACK_PORT,
    })
  );

  const error = query.get("error");
  if (error) {
    // access_denied is the user pressing Cancel — not a bug, and worth phrasing
    // as such rather than showing a raw OAuth error code.
    throw new AuthError(
      error === "access_denied"
        ? "You declined the authorization request."
        : `Spotify returned an error: ${error}`
    );
  }
  if (query.get("state") !== request.state) {
    throw new AuthError("State mismatch on the OAuth callback — authorization was not completed.");
  }
  const code = query.get("code");
  if (!code) throw new AuthError("The OAuth callback contained no authorization code.");

  const tokens = await exchangeCode(clientId, code, request.verifier, fetch, CALLBACK_PORT);

  // Encrypt before the tokens touch the network. D1 only ever sees ciphertext,
  // and the Worker cron decrypts with this same implementation.
  const fernetKey = await invoke<string>("encryption_key");
  const userId = await currentUserId(tokens.access_token);

  const res = await fetch(
    `${cfg.worker_url}/api/tokens?user_id=${encodeURIComponent(userId)}`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${cfg.worker_auth_token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        access_token: await fernetEncrypt(tokens.access_token, fernetKey),
        refresh_token: await fernetEncrypt(tokens.refresh_token, fernetKey),
        expires_at: expiresAt(tokens.expires_in),
        scopes: tokens.scope ?? "",
      }),
    }
  );
  if (!res.ok) {
    throw new AuthError(
      `Authorized with Spotify, but storing the tokens failed: HTTP ${res.status}. ` +
        "Check Cloud sync and try again."
    );
  }

  // The Worker cron reads SPOTIFY_USER_ID to find the row it just wrote.
  await invoke("set_config", { pairs: [`SPOTIFY_USER_ID=${userId}`] });
  return { userId };
}

/**
 * The authorizing account's Spotify id, used as the `spotify_tokens` primary key.
 *
 * Worth one extra call: the old flow keyed every row as "default", so a token
 * row and a configured SPOTIFY_USER_ID could disagree, and the only symptom was
 * a cron sync that silently found no tokens.
 */
async function currentUserId(accessToken: string): Promise<string> {
  const res = await fetch("https://api.spotify.com/v1/me", {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (!res.ok) throw new AuthError(`Could not read your Spotify profile: HTTP ${res.status}`);
  const me = (await res.json()) as { id?: string };
  if (!me.id) throw new AuthError("Spotify returned a profile with no id.");
  return me.id;
}
