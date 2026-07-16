// Worker API client. In dev the Vite proxy forwards /api -> Worker and adds
// the Bearer header (see vite.config.ts); if no Worker is configured the app
// falls back to generated sample data so the shell renders standalone.

// Mirror of the Worker's row shape (worker/src/tracks.ts). Deliberately
// copied, not imported — the two packages keep separate dependency trees;
// extract a shared types file if this surface ever grows past one interface.
export interface TrackRow {
  id: string;
  track_id: string;
  track_name?: string | null;
  artist_name?: string | null;
  album_name?: string | null;
  played_at: string; // ISO-8601 UTC
  ms_played?: number | null;
  source?: string | null;
}

/** GET /api/tracks?from=&to= (ISO strings, inclusive). Throws on any failure. */
export async function fetchTracks(fromIso: string, toIso: string): Promise<TrackRow[]> {
  const params = new URLSearchParams({ from: fromIso, to: toIso });
  const res = await fetch(`/api/tracks?${params}`);
  if (!res.ok) throw new Error(`Worker responded ${res.status}`);
  const body = await res.json();
  return body.tracks as TrackRow[];
}

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
