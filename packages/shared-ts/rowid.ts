// The `listening_history.id` primary key, in one place.
//
// The same play can arrive from three sources — the Worker cron (Spotify API),
// a Spotify data-export import, and a re-sync of either — and all three must
// produce the *same* id, because `INSERT OR IGNORE` on that id is the only thing
// keeping duplicates out. A disagreement of one character means the same listen
// counted twice, silently, in every chart.
//
// The format is fixed by history: sha1("<track_uri>:<seconds-precision UTC ISO>").
// Python's `pipeline.parse_api_item` established it, so changing it would
// duplicate every row already in D1.

/** Lowercase hex SHA-1. */
export async function sha1Hex(s: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-1", new TextEncoder().encode(s));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

/**
 * Seconds-precision UTC ISO, matching Python's
 * `strftime("%Y-%m-%dT%H:%M:%SZ")`. Milliseconds must be dropped, not rounded:
 * the export and the API report the same play with different sub-second parts.
 */
export function playedAtIso(playedAtMs: number): string {
  return new Date(playedAtMs).toISOString().replace(/\.\d{3}Z$/, "Z");
}

/** The `listening_history.id` for one play. */
export function playRowId(trackUri: string, playedAtIsoValue: string): Promise<string> {
  return sha1Hex(`${trackUri}:${playedAtIsoValue}`);
}
