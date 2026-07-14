export interface Env {
  AUTH_TOKEN: string;
}

/**
 * Guards a request with a static Bearer token.
 *
 * Returns a 401 Response if the `Authorization` header is not exactly
 * `Bearer <env.AUTH_TOKEN>`, or `null` if the request is authorized.
 */
export function requireAuth(request: Request, env: Env): Response | null {
  const header = request.headers.get("Authorization");

  if (!env.AUTH_TOKEN || header !== `Bearer ${env.AUTH_TOKEN}`) {
    return new Response("Unauthorized", { status: 401 });
  }

  return null;
}
