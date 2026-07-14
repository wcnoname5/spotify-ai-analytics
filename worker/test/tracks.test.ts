import { env, SELF } from "cloudflare:test";
import { beforeEach, describe, expect, it } from "vitest";

const AUTH_HEADERS = { Authorization: `Bearer ${env.AUTH_TOKEN}` };
const JSON_HEADERS = { ...AUTH_HEADERS, "Content-Type": "application/json" };

function makeTrack(overrides: Record<string, unknown> = {}) {
  return {
    id: "play-1",
    track_id: "track-1",
    track_name: "Song",
    artist_name: "Artist",
    album_name: "Album",
    played_at: "2026-01-01T00:00:00.000Z",
    ms_played: 1000,
    source: "api",
    platform: "web",
    conn_country: "US",
    reason_start: "trackdone",
    reason_end: "trackdone",
    shuffle: 0,
    skipped: 0,
    ...overrides,
  };
}

beforeEach(async () => {
  await env.DB.exec("DELETE FROM listening_history");
});

describe("router auth", () => {
  it("returns 401 when no bearer token is supplied", async () => {
    const response = await SELF.fetch("https://example.com/api/tracks/count");
    expect(response.status).toBe(401);
  });
});

describe("unknown routes", () => {
  it("returns 404", async () => {
    const response = await SELF.fetch("https://example.com/api/nope", {
      headers: AUTH_HEADERS,
    });
    expect(response.status).toBe(404);
  });
});

describe("POST /api/tracks + GET /api/tracks", () => {
  it("inserts a track and returns it from a since query", async () => {
    const postResponse = await SELF.fetch("https://example.com/api/tracks", {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify({ tracks: [makeTrack()] }),
    });

    expect(postResponse.status).toBe(200);
    expect(await postResponse.json()).toEqual({ inserted: 1 });

    const since = Date.parse("2025-12-31T00:00:00.000Z");
    const getResponse = await SELF.fetch(
      `https://example.com/api/tracks?since=${since}`,
      { headers: AUTH_HEADERS }
    );

    expect(getResponse.status).toBe(200);
    const body = (await getResponse.json()) as { tracks: { id: string }[] };
    expect(body.tracks).toHaveLength(1);
    expect(body.tracks[0].id).toBe("play-1");
  });

  it("returns rows within a from/to range", async () => {
    await SELF.fetch("https://example.com/api/tracks", {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify({ tracks: [makeTrack()] }),
    });

    const from = Date.parse("2025-12-31T00:00:00.000Z");
    const to = Date.parse("2026-01-02T00:00:00.000Z");
    const response = await SELF.fetch(
      `https://example.com/api/tracks?from=${from}&to=${to}`,
      { headers: AUTH_HEADERS }
    );

    expect(response.status).toBe(200);
    const body = (await response.json()) as { tracks: { id: string }[] };
    expect(body.tracks).toHaveLength(1);
  });

  it("returns 400 for a malformed JSON body", async () => {
    const response = await SELF.fetch("https://example.com/api/tracks", {
      method: "POST",
      headers: JSON_HEADERS,
      body: "not json",
    });

    expect(response.status).toBe(400);
  });

  it("returns 400 when a track is missing required fields", async () => {
    const response = await SELF.fetch("https://example.com/api/tracks", {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify({ tracks: [{ track_name: "no id" }] }),
    });

    expect(response.status).toBe(400);
  });
});

describe("duplicate-id idempotency", () => {
  it("ignores rows with an id already present and keeps the count stable", async () => {
    const post = () =>
      SELF.fetch("https://example.com/api/tracks", {
        method: "POST",
        headers: JSON_HEADERS,
        body: JSON.stringify({ tracks: [makeTrack()] }),
      });

    const first = await post();
    expect(await first.json()).toEqual({ inserted: 1 });

    const second = await post();
    expect(await second.json()).toEqual({ inserted: 0 });

    const countResponse = await SELF.fetch(
      "https://example.com/api/tracks/count",
      { headers: AUTH_HEADERS }
    );
    expect(await countResponse.json()).toEqual({ count: 1 });
  });
});

describe("GET /api/tracks/count", () => {
  it("returns 0 when the table is empty", async () => {
    const response = await SELF.fetch("https://example.com/api/tracks/count", {
      headers: AUTH_HEADERS,
    });

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ count: 0 });
  });
});
