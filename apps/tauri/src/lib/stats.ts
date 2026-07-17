// Pure formatters shared by both the Tauri (SQL-backed) and sample-data rendering paths.
// Aggregation now happens in SQL (queries.ts) or, for the sample fallback, in api.ts's sampleStats/sampleRecentPlays.

/** % change vs a previous value; null when there is no baseline. */
export function delta(current: number, previous: number): number | null {
  if (previous === 0) return null;
  return ((current - previous) / previous) * 100;
}

export function formatMinutes(min: number): string {
  if (min < 60) return `${min}m`;
  return `${Math.floor(min / 60)}h ${min % 60}m`;
}

export function spotifyUrl(trackId: string): string {
  return `https://open.spotify.com/track/${trackId.replace(/^spotify:track:/, "")}`;
}
