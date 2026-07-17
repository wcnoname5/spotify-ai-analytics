// Thin async wrappers around the shared .sql/ files (packages/core/spotify_core/db/sql),
// imported as raw text via the `@sql` alias and run against the local cache DB (db.ts).
// Param order convention: ?1=start, ?2=end, ?3=tz modifier (where used),
// trailing params (LIMIT, ...) after.
import listeningSummarySql from "@sql/listening_summary.sql?raw";
import topArtistsSql from "@sql/top_artists.sql?raw";
import topTracksSql from "@sql/top_tracks.sql?raw";
import recentPlaysSql from "@sql/recent_plays.sql?raw";
import trendDailySql from "@sql/trend_daily.sql?raw";
import trendWeeklySql from "@sql/trend_weekly.sql?raw";
import trendMonthlySql from "@sql/trend_monthly.sql?raw";
import playsByHourSql from "@sql/plays_by_hour.sql?raw";
import dataRangeSql from "@sql/data_range.sql?raw";
import { getDb } from "./db";

export interface Range {
  start: string | null;
  end: string | null;
}

export type Granularity = "day" | "week" | "month";

export interface DataRange {
  earliest: string | null;
  latest: string | null;
}

/** SQLite `datetime(..., modifier)` string for the browser's local UTC offset. */
function tzModifier(): string {
  const off = -new Date().getTimezoneOffset() / 60;
  return `${off >= 0 ? "+" : ""}${off} hours`;
}

export interface ListeningSummary {
  total_plays: number;
  unique_tracks: number;
  unique_artists: number;
  earliest_played_at: string | null;
  latest_played_at: string | null;
  total_mins_played: number | null;
  avg_mins_per_play: number | null;
  skip_rate: number | null;
}

export async function listeningSummary(range: Range): Promise<ListeningSummary> {
  const db = await getDb();
  const rows = await db.select<ListeningSummary[]>(listeningSummarySql, [range.start, range.end]);
  return rows[0];
}

export interface TopArtist {
  artist_name: string;
  total_mins: number;
  play_count: number;
}

export async function topArtists(range: Range, limit: number): Promise<TopArtist[]> {
  const db = await getDb();
  return db.select<TopArtist[]>(topArtistsSql, [range.start, range.end, limit]);
}

export interface TopTrack {
  track_id: string;
  track_name: string;
  artist_name: string | null;
  play_count: number;
  total_mins: number;
}

export async function topTracks(range: Range, limit: number): Promise<TopTrack[]> {
  const db = await getDb();
  return db.select<TopTrack[]>(topTracksSql, [range.start, range.end, limit]);
}

export interface RecentPlay {
  track_name: string;
  artist_name: string | null;
  album_name: string | null;
  played_at: string;
  ms_played: number | null;
  track_id: string;
}

export async function recentPlays(limit: number): Promise<RecentPlay[]> {
  const db = await getDb();
  return db.select<RecentPlay[]>(recentPlaysSql, [null, null, limit]);
}

export interface TrendPoint {
  bucket: string;
  total_mins: number;
  play_count: number;
}

const TREND_SQL: Record<Granularity, string> = {
  day: trendDailySql,
  week: trendWeeklySql,
  month: trendMonthlySql,
};

export async function trend(range: Range, granularity: Granularity): Promise<TrendPoint[]> {
  const db = await getDb();
  return db.select<TrendPoint[]>(TREND_SQL[granularity], [range.start, range.end, tzModifier()]);
}

export interface PlaysByHour {
  hour: number;
  play_count: number;
  total_mins: number;
}

export async function playsByHour(range: Range): Promise<PlaysByHour[]> {
  const db = await getDb();
  return db.select<PlaysByHour[]>(playsByHourSql, [range.start, range.end, tzModifier()]);
}

/** Global min/max played_at — drives the date inputs' min/max validation. */
export async function dataRange(): Promise<DataRange> {
  const db = await getDb();
  const rows = await db.select<DataRange[]>(dataRangeSql, []);
  return rows[0];
}
