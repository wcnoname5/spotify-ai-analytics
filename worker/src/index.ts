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
import { handleGetReports, handlePostReport } from "./reports";
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
    if (pathname === "/api/reports" && method === "GET") {
      return handleGetReports(request, env);
    }
    if (pathname === "/api/reports" && method === "POST") {
      return handlePostReport(request, env);
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
    // The same work the hourly cron does, on demand. The app offers it right
    // after authorizing so a new user is not looking at an empty dashboard until
    // the next tick. It replaced a local `spotify-mcp sync`, which needed a copy
    // of the tokens on the user's machine.
    if (pathname === "/api/sync" && method === "POST") {
      try {
        return Response.json(await runSync(env));
      } catch (e) {
        // The actionable cases are "no token row yet" and an expired refresh
        // token; both are worth showing the user rather than a bare 500.
        return Response.json({ error: (e as Error).message }, { status: 502 });
      }
    }

    return new Response("Not Found", { status: 404 });
  },

  // Hourly Spotify -> D1 sync. Awaited (not waitUntil) so a failure marks the invocation failed in Cron Events.
  async scheduled(_controller, env, _ctx): Promise<void> {
    const result = await runSync(env);
    console.log(
      `cron sync: inserted=${result.inserted} skipped_parse_error=${result.skippedParseError} cursor=${result.cursorMs}`
    );
  },
} satisfies ExportedHandler<Env>;
