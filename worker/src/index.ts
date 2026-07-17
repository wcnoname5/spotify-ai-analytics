import { requireAuth } from "./auth";
import {
  handleGetTracks,
  handleGetTracksCount,
  handlePostTracks,
} from "./tracks";
import {
  handleGetCursor,
  handleGetTokens,
  handlePostCursor,
  handlePostTokens,
} from "./tokens";
import { runSync } from "./sync";

export interface Env {
  DB: D1Database;
  AUTH_TOKEN: string;
  SPOTIFY_CLIENT_ID: string;
  TOKEN_ENCRYPT_KEY: string;
  SPOTIFY_USER_ID?: string;
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const unauthorized = requireAuth(request, env);
    if (unauthorized) return unauthorized;

    const { pathname } = new URL(request.url);
    const { method } = request;

    if (pathname === "/api/tracks/count" && method === "GET") {
      return handleGetTracksCount(request, env);
    }
    if (pathname === "/api/tracks" && method === "GET") {
      return handleGetTracks(request, env);
    }
    if (pathname === "/api/tracks" && method === "POST") {
      return handlePostTracks(request, env);
    }
    if (pathname === "/api/tokens" && method === "GET") {
      return handleGetTokens(request, env);
    }
    if (pathname === "/api/tokens" && method === "POST") {
      return handlePostTokens(request, env);
    }
    if (pathname === "/api/cursor" && method === "GET") {
      return handleGetCursor(request, env);
    }
    if (pathname === "/api/cursor" && method === "POST") {
      return handlePostCursor(request, env);
    }

    return new Response("Not Found", { status: 404 });
  },

  // Hourly Spotify -> D1 sync (replaces the GH Actions cron). Awaited (not
  // waitUntil) so a failure marks the invocation failed in Cron Events.
  async scheduled(_controller, env, _ctx): Promise<void> {
    const result = await runSync(env);
    // logs row counts.
    console.log(
      `cron sync: inserted=${result.inserted} skipped_parse_error=${result.skippedParseError} cursor=${result.cursorMs}`
    );
  },
} satisfies ExportedHandler<Env>;
