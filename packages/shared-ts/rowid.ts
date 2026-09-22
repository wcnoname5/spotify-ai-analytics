// The `listening_history.id` primary key
//
// The format is fixed by history: sha1("<track_uri>:<seconds-precision UTC ISO>").

/** Lowercase hex SHA-1. */
export async function sha1Hex(s: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-1", new TextEncoder().encode(s));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

/**
 * Seconds-precision UTC ISO. Milliseconds dropped.
 * the export and the API report the same play with different sub-second parts.
 */
export function playedAtIso(playedAtMs: number): string {
  return new Date(playedAtMs).toISOString().replace(/\.\d{3}Z$/, "Z");
}

/** The `listening_history.id` for one play. */
export function playRowId(trackUri: string, playedAtIsoValue: string): Promise<string> {
  return sha1Hex(`${trackUri}:${playedAtIsoValue}`);
}
