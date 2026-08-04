import { describe, expect, it } from "vitest";

import {
  buildAuthRequest,
  challengeFor,
  createState,
  createVerifier,
  exchangeCode,
  expiresAt,
  redirectUri,
} from "./pkce";

describe("challengeFor", () => {
  it("matches the RFC 7636 appendix B test vector", async () => {
    // The one check that actually proves S256 is implemented correctly: a wrong
    // digest, a wrong encoding, or stray padding all fail here, and Spotify
    // would otherwise only tell us "invalid_grant" at the exchange step.
    expect(await challengeFor("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk")).toBe(
      "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    );
  });

  it("emits unpadded base64url", async () => {
    const challenge = await challengeFor(createVerifier());
    expect(challenge).not.toContain("=");
    expect(challenge).toMatch(/^[A-Za-z0-9_-]+$/);
  });
});

describe("createVerifier", () => {
  it("is 43 chars of unreserved characters, the RFC minimum", () => {
    const verifier = createVerifier();
    expect(verifier).toHaveLength(43);
    expect(verifier).toMatch(/^[A-Za-z0-9_-]+$/);
  });

  it("does not repeat", () => {
    const seen = new Set(Array.from({ length: 50 }, () => createVerifier()));
    expect(seen.size).toBe(50);
  });
});

describe("redirectUri", () => {
  it("uses 127.0.0.1, never localhost", () => {
    // Spotify rejected `localhost` in Nov 2025, and the failure is a wall of
    // "INVALID_CLIENT: Invalid redirect URI" with no hint about which part.
    expect(redirectUri()).toBe("http://127.0.0.1:8888/callback");
    expect(redirectUri()).not.toContain("localhost");
  });
});

describe("buildAuthRequest", () => {
  it("asks for S256 and carries a challenge derived from its own verifier", async () => {
    const req = await buildAuthRequest("client-abc");
    const params = new URL(req.url).searchParams;

    expect(params.get("client_id")).toBe("client-abc");
    expect(params.get("response_type")).toBe("code");
    expect(params.get("code_challenge_method")).toBe("S256");
    expect(params.get("redirect_uri")).toBe("http://127.0.0.1:8888/callback");
    // The verifier returned to the caller must be the one this challenge came
    // from, or the exchange fails after the user has already authorized.
    expect(params.get("code_challenge")).toBe(await challengeFor(req.verifier));
    expect(params.get("state")).toBe(req.state);
  });

  it("requests only scopes the app uses", async () => {
    const scope = new URL((await buildAuthRequest("c")).url).searchParams.get("scope");
    expect(scope).toContain("user-read-recently-played");
    // Anything beyond playback + recently-played would be asking the user to
    // approve capabilities that do not exist.
    expect(scope).not.toContain("playlist");
    expect(scope).not.toContain("user-follow");
  });
});

describe("createState", () => {
  it("does not repeat", () => {
    const seen = new Set(Array.from({ length: 50 }, () => createState()));
    expect(seen.size).toBe(50);
  });
});

describe("exchangeCode", () => {
  const ok = (body: unknown): typeof fetch =>
    (async () => new Response(JSON.stringify(body), { status: 200 })) as unknown as typeof fetch;

  it("posts the verifier and the same redirect_uri the authorize step used", async () => {
    let seen: URLSearchParams | undefined;
    const spy = (async (_url: string, init: RequestInit) => {
      seen = new URLSearchParams(init.body as string);
      return new Response(
        JSON.stringify({ access_token: "at", refresh_token: "rt", expires_in: 3600 }),
        { status: 200 }
      );
    }) as unknown as typeof fetch;

    await exchangeCode("client-abc", "the-code", "the-verifier", spy);

    expect(seen?.get("grant_type")).toBe("authorization_code");
    expect(seen?.get("code")).toBe("the-code");
    expect(seen?.get("code_verifier")).toBe("the-verifier");
    // A redirect_uri that differs from the authorize request by even a trailing
    // slash is rejected, and Spotify does not say which one it disliked.
    expect(seen?.get("redirect_uri")).toBe("http://127.0.0.1:8888/callback");
  });

  it("rejects a response with no refresh_token", async () => {
    // The hourly cron has nothing to refresh with in that case, so every later
    // sync would fail. Better to fail now, where retrying is free.
    await expect(
      exchangeCode("c", "code", "v", ok({ access_token: "at", expires_in: 3600 }))
    ).rejects.toThrow(/refresh_token/);
  });

  it("surfaces the response body, not just the status", async () => {
    const failing = (async () =>
      new Response("invalid_grant", { status: 400 })) as unknown as typeof fetch;
    await expect(exchangeCode("c", "code", "v", failing)).rejects.toThrow(/invalid_grant/);
  });
});

describe("expiresAt", () => {
  it("is UTC ISO 8601, matching the spotify_tokens column", () => {
    expect(expiresAt(3600, Date.parse("2026-01-01T00:00:00Z"))).toBe("2026-01-01T01:00:00.000Z");
  });
});
