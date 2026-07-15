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

export interface Env {
  DB: D1Database;
  AUTH_TOKEN: string;
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
} satisfies ExportedHandler<Env>;
