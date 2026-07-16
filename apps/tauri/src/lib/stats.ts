// Pure aggregate functions over TrackRow[] — computed client-side for now.
// ponytail: fine at personal scale (<100k rows); move to Worker aggregate
// endpoints when "All time" payloads get heavy (see App.vue data loading).
import type { TrackRow } from "./api";

export interface Metrics {
  plays: number;
  minutes: number;
  uniqueArtists: number;
  uniqueTracks: number;
}

export function metrics(rows: TrackRow[]): Metrics {
  const artists = new Set<string>();
  const tracks = new Set<string>();
  let ms = 0;
  for (const r of rows) {
    if (r.artist_name) artists.add(r.artist_name);
    tracks.add(r.track_id);
    ms += r.ms_played ?? 0;
  }
  return {
    plays: rows.length,
    minutes: Math.round(ms / 60_000),
    uniqueArtists: artists.size,
    uniqueTracks: tracks.size,
  };
}

/** % change vs a previous value; null when there is no baseline. */
export function delta(current: number, previous: number): number | null {
  if (previous === 0) return null;
  return ((current - previous) / previous) * 100;
}

export function topArtistsByTime(rows: TrackRow[], limit = 10): { artist: string; minutes: number }[] {
  const byArtist = new Map<string, number>();
  for (const r of rows) {
    if (!r.artist_name) continue;
    byArtist.set(r.artist_name, (byArtist.get(r.artist_name) ?? 0) + (r.ms_played ?? 0));
  }
  return [...byArtist.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, limit)
    .map(([artist, ms]) => ({ artist, minutes: Math.round(ms / 60_000) }));
}

export function topTracksByPlays(
  rows: TrackRow[],
  limit = 10
): { track: string; artist: string; plays: number; trackId: string }[] {
  const byTrack = new Map<string, { track: string; artist: string; plays: number; trackId: string }>();
  for (const r of rows) {
    const entry = byTrack.get(r.track_id) ?? {
      track: r.track_name ?? r.track_id,
      artist: r.artist_name ?? "",
      plays: 0,
      trackId: r.track_id,
    };
    entry.plays += 1;
    byTrack.set(r.track_id, entry);
  }
  return [...byTrack.values()].sort((a, b) => b.plays - a.plays).slice(0, limit);
}

/** Plays per local hour of day, 0..23. */
export function playsByHour(rows: TrackRow[]): number[] {
  const hours = new Array(24).fill(0);
  for (const r of rows) hours[new Date(r.played_at).getHours()] += 1;
  return hours;
}

/** Listening minutes per local calendar day, sorted ascending. */
export function minutesByDay(rows: TrackRow[]): { day: string; minutes: number }[] {
  const byDay = new Map<string, number>();
  for (const r of rows) {
    const d = new Date(r.played_at);
    const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    byDay.set(key, (byDay.get(key) ?? 0) + (r.ms_played ?? 0));
  }
  return [...byDay.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([day, ms]) => ({ day, minutes: Math.round(ms / 60_000) }));
}

export function formatMinutes(min: number): string {
  if (min < 60) return `${min}m`;
  return `${Math.floor(min / 60)}h ${min % 60}m`;
}

export function spotifyUrl(trackId: string): string {
  return `https://open.spotify.com/track/${trackId.replace(/^spotify:track:/, "")}`;
}
