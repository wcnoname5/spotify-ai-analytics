// Sample-data fallback for browser dev (`npm run dev`, no Tauri runtime). The
// real Worker/D1 API path lives in sync.ts (startup sync into local SQLite);
// this module produces deterministic sample rows and aggregates them into the same shapes queries.ts returns
// App.vue can render standalone without Tauri.
import type {
  Range,
  ListeningSummary,
  TopArtist,
  TopTrack,
  RecentPlay,
  TrendPoint,
  PlaysByHour,
  Granularity,
} from "./queries";

// listening history rows, as returned by the Worker/D1 API and inserted into local SQLite.
export interface TrackRow {
  id: string;
  track_id: string;
  track_name?: string | null;
  artist_name?: string | null;
  album_name?: string | null;
  played_at: string; // ISO-8601 UTC
  ms_played?: number | null;
  source?: string | null;
  platform?: string | null;
  conn_country?: string | null;
  reason_start?: string | null;
  reason_end?: string | null;
  shuffle?: number | null;
  skipped?: number | null;
}

// TODO: sample can be deleted in the future.
const SAMPLE_EPOCH = "2008-01-01T00:00:00Z"; // before Spotify existed — "all time"

/** Deterministic sample data so the shell is workable without a Worker. */
export function sampleTracks(fromIso: string, toIso: string): TrackRow[] {
  const artists = [
    ["トリプルファイヤー", "Live on Fire"],
    ["Fishmans", "宇宙 日本 世田谷"],
    ["Radiohead", "In Rainbows"],
    ["坂本慎太郎", "できれば愛を"],
    ["Stereolab", "Dots and Loops"],
    ["Broadcast", "Tender Buttons"],
  ] as const;
  const rows: TrackRow[] = [];
  const start = Date.parse(fromIso);
  const end = Math.min(Date.parse(toIso), Date.now());
  let seed = 42;
  const rand = () => (seed = (seed * 1103515245 + 12345) % 2 ** 31) / 2 ** 31;
  for (let t = start; t < end; t += 3600_000) {
    const hour = new Date(t).getUTCHours();
    const playsThisHour = rand() < (hour > 10 && hour < 16 ? 0.7 : 0.15) ? Math.ceil(rand() * 4) : 0;
    for (let i = 0; i < playsThisHour; i++) {
      const [artist, album] = artists[Math.floor(rand() * artists.length)];
      const n = Math.floor(rand() * 8);
      rows.push({
        id: `sample-${t}-${i}`,
        track_id: `sample${n}`,
        track_name: `${artist} — Track ${n + 1}`,
        artist_name: artist,
        album_name: album,
        played_at: new Date(t + i * 60_000).toISOString(),
        ms_played: 120_000 + Math.floor(rand() * 180_000),
        source: "sample",
      });
    }
  }
  return rows;
}

export interface SampleData {
  summary: ListeningSummary;
  topArtists: TopArtist[];
  topTracks: TopTrack[];
  dailyTrend: TrendPoint[];
  playsByHour: PlaysByHour[];
}

function trendKey(d: Date, g: Granularity): string {
  if (g === "month")
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
  const day = new Date(d);
  if (g === "week") day.setDate(day.getDate() - ((day.getDay() + 6) % 7)); // back to Monday
  return `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, "0")}-${String(day.getDate()).padStart(2, "0")}`;
}

/** Aggregates sample rows for `range` into the same shapes queries.ts returns. */
export function sampleStats(range: Range, limit = 10, granularity: Granularity = "day"): SampleData {
  const fromIso = range.start ?? SAMPLE_EPOCH;
  const toIso = range.end ?? new Date().toISOString();
  const rows = sampleTracks(fromIso, toIso);
  const byTime = [...rows].sort((a, b) => a.played_at.localeCompare(b.played_at));

  const artistSet = new Set<string>();
  const trackSet = new Set<string>();
  let totalMs = 0;
  for (const r of rows) {
    if (r.artist_name) artistSet.add(r.artist_name);
    trackSet.add(r.track_id);
    totalMs += r.ms_played ?? 0;
  }
  const summary: ListeningSummary = {
    total_plays: rows.length,
    unique_tracks: trackSet.size,
    unique_artists: artistSet.size,
    earliest_played_at: byTime[0]?.played_at ?? null,
    latest_played_at: byTime[byTime.length - 1]?.played_at ?? null,
    total_mins_played: rows.length ? Math.round(totalMs / 60_000) : null,
    avg_mins_per_play: rows.length ? totalMs / 60_000 / rows.length : null,
    skip_rate: null,
  };

  const byArtist = new Map<string, { mins: number; plays: number }>();
  for (const r of rows) {
    if (!r.artist_name) continue;
    const e = byArtist.get(r.artist_name) ?? { mins: 0, plays: 0 };
    e.mins += (r.ms_played ?? 0) / 60_000;
    e.plays += 1;
    byArtist.set(r.artist_name, e);
  }
  const topArtists: TopArtist[] = [...byArtist.entries()]
    .sort((a, b) => b[1].mins - a[1].mins)
    .slice(0, limit)
    .map(([artist_name, e]) => ({
      artist_name,
      total_mins: Math.round(e.mins),
      play_count: e.plays,
    }));

  const byTrack = new Map<string, TopTrack>();
  for (const r of rows) {
    const e = byTrack.get(r.track_id) ?? {
      track_id: r.track_id,
      track_name: r.track_name ?? r.track_id,
      artist_name: r.artist_name ?? null,
      play_count: 0,
      total_mins: 0,
    };
    e.play_count += 1;
    e.total_mins += Math.round((r.ms_played ?? 0) / 60_000);
    byTrack.set(r.track_id, e);
  }
  const topTracks: TopTrack[] = [...byTrack.values()]
    .sort((a, b) => b.play_count - a.play_count)
    .slice(0, limit);

  const byDay = new Map<string, { mins: number; plays: number }>();
  for (const r of rows) {
    const d = new Date(r.played_at);
    const key = trendKey(d, granularity);
    const e = byDay.get(key) ?? { mins: 0, plays: 0 };
    e.mins += (r.ms_played ?? 0) / 60_000;
    e.plays += 1;
    byDay.set(key, e);
  }
  const dailyTrend: TrendPoint[] = [...byDay.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([bucket, e]) => ({ bucket, total_mins: Math.round(e.mins), play_count: e.plays }));

  const hourAgg = Array.from({ length: 24 }, () => ({ plays: 0, mins: 0 }));
  for (const r of rows) {
    const h = new Date(r.played_at).getHours();
    hourAgg[h].plays += 1;
    hourAgg[h].mins += (r.ms_played ?? 0) / 60_000;
  }
  const playsByHour: PlaysByHour[] = hourAgg.map((e, hour) => ({
    hour,
    play_count: e.plays,
    total_mins: Math.round(e.mins),
  }));

  return { summary, topArtists, topTracks, dailyTrend, playsByHour };
}

/** Sample "Recently Played" list — ignores `range`, mirroring queries.recentPlays. */
export function sampleRecentPlays(limit: number): RecentPlay[] {
  const rows = sampleTracks(SAMPLE_EPOCH, new Date().toISOString());
  return [...rows]
    .sort((a, b) => b.played_at.localeCompare(a.played_at))
    .slice(0, limit)
    .map((r) => ({
      track_name: r.track_name ?? r.track_id,
      artist_name: r.artist_name ?? null,
      album_name: r.album_name ?? null,
      played_at: r.played_at,
      ms_played: r.ms_played ?? null,
      track_id: r.track_id,
    }));
}
