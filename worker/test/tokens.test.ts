import { env, SELF } from "cloudflare:test";
import { beforeEach, describe, expect, it } from "vitest";

const AUTH_HEADERS = { Authorization: `Bearer ${env.AUTH_TOKEN}` };
const JSON_HEADERS = { ...AUTH_HEADERS, "Content-Type": "application/json" };

function makeTokenRow(overrides: Record<string, unknown> = {}) {
  return {
    user_id: "default",
    access_token: "enc-access-1",
    refresh_token: "enc-refresh-1",
    expires_at: "2026-01-01T00:00:00.000Z",
    scopes: "user-read-recently-played",
    ...overrides,
  };
}

beforeEach(async () => {
  await env.DB.exec("DELETE FROM spotify_tokens");
  await env.DB.exec("DELETE FROM sync_state");
});

describe("POST /api/tokens + GET /api/tokens", () => {
  it("round-trips a token row as ciphertext passthrough", async () => {
    const postResponse = await SELF.fetch(
      "https://example.com/api/tokens?user_id=default",
      {
        method: "POST",
        headers: JSON_HEADERS,
        body: JSON.stringify(makeTokenRow()),
      }
    );
    expect(postResponse.status).toBe(200);

    const getResponse = await SELF.fetch(
      "https://example.com/api/tokens?user_id=default",
      { headers: AUTH_HEADERS }
    );
    expect(getResponse.status).toBe(200);
    const body = await getResponse.json();
    expect(body).toEqual(makeTokenRow());
  });

  it("upserts (overwrites) an existing row for the same user_id", async () => {
    await SELF.fetch("https://example.com/api/tokens?user_id=default", {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify(makeTokenRow()),
    });

    const updated = makeTokenRow({
      access_token: "enc-access-2",
      refresh_token: "enc-refresh-2",
    });
    const postResponse = await SELF.fetch(
      "https://example.com/api/tokens?user_id=default",
      {
        method: "POST",
        headers: JSON_HEADERS,
        body: JSON.stringify(updated),
      }
    );
    expect(postResponse.status).toBe(200);

    const getResponse = await SELF.fetch(
      "https://example.com/api/tokens?user_id=default",
      { headers: AUTH_HEADERS }
    );
    const body = await getResponse.json();
    expect(body).toEqual(updated);

    const countRow = await env.DB.prepare(
      "SELECT COUNT(*) AS count FROM spotify_tokens"
    ).first<{ count: number }>();
    expect(countRow?.count).toBe(1);
  });

  it("returns 404 when the token row is missing", async () => {
    const response = await SELF.fetch(
      "https://example.com/api/tokens?user_id=missing-user",
      { headers: AUTH_HEADERS }
    );
    expect(response.status).toBe(404);
    const body = (await response.json()) as { error: string };
    expect(body.error).toBeTruthy();
  });

  it("returns 400 for a malformed JSON body", async () => {
    const response = await SELF.fetch(
      "https://example.com/api/tokens?user_id=default",
      {
        method: "POST",
        headers: JSON_HEADERS,
        body: "not json",
      }
    );
    expect(response.status).toBe(400);
  });

  it("returns 400 when required fields are missing", async () => {
    const response = await SELF.fetch(
      "https://example.com/api/tokens?user_id=default",
      {
        method: "POST",
        headers: JSON_HEADERS,
        body: JSON.stringify({ access_token: "only-this" }),
      }
    );
    expect(response.status).toBe(400);
  });
});

describe("GET /api/cursor + POST /api/cursor", () => {
  it("defaults to 0 when no sync_state row exists", async () => {
    const response = await SELF.fetch("https://example.com/api/cursor", {
      headers: AUTH_HEADERS,
    });
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ last_played_at_ms: 0 });
  });

  it("advances the cursor via POST and reflects it on GET", async () => {
    const postResponse = await SELF.fetch("https://example.com/api/cursor", {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify({ last_played_at_ms: 1735689600000 }),
    });
    expect(postResponse.status).toBe(200);

    const getResponse = await SELF.fetch("https://example.com/api/cursor", {
      headers: AUTH_HEADERS,
    });
    expect(await getResponse.json()).toEqual({
      last_played_at_ms: 1735689600000,
    });
  });

  it("upserts the cursor on repeated POSTs", async () => {
    await SELF.fetch("https://example.com/api/cursor", {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify({ last_played_at_ms: 100 }),
    });
    await SELF.fetch("https://example.com/api/cursor", {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify({ last_played_at_ms: 200 }),
    });

    const getResponse = await SELF.fetch("https://example.com/api/cursor", {
      headers: AUTH_HEADERS,
    });
    expect(await getResponse.json()).toEqual({ last_played_at_ms: 200 });

    const countRow = await env.DB.prepare(
      "SELECT COUNT(*) AS count FROM sync_state"
    ).first<{ count: number }>();
    expect(countRow?.count).toBe(1);
  });

  it("returns 400 for a malformed JSON body", async () => {
    const response = await SELF.fetch("https://example.com/api/cursor", {
      method: "POST",
      headers: JSON_HEADERS,
      body: "not json",
    });
    expect(response.status).toBe(400);
  });

  it("returns 400 when last_played_at_ms is missing or not a number", async () => {
    const response = await SELF.fetch("https://example.com/api/cursor", {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify({ last_played_at_ms: "not-a-number" }),
    });
    expect(response.status).toBe(400);
  });
});
