<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import PlotChart from "./components/PlotChart.vue";
import { sampleRecentPlays, sampleStats } from "./lib/api";
import { isTauri } from "./lib/db";
import { syncOnStartup } from "./lib/sync";
import {
  dailyTrend,
  listeningSummary,
  playsByHour,
  recentPlays,
  topArtists,
  topTracks,
  type DailyTrend,
  type ListeningSummary,
  type PlaysByHour,
  type Range,
  type RecentPlay,
  type TopArtist,
  type TopTrack,
} from "./lib/queries";
import { delta, formatMinutes, spotifyUrl } from "./lib/formatters";

type RangeKey = "7" | "30" | "90" | "all";
const RANGES: { key: RangeKey; label: string }[] = [
  { key: "7", label: "7 days" },
  { key: "30", label: "30 days" },
  { key: "90", label: "90 days" },
  { key: "all", label: "All time" },
];

const range = ref<RangeKey>("30");
const loading = ref(false);
const usingSample = ref(false);
const offlineNotice = ref<"unconfigured" | "error" | null>(null);
const loadFailedNotice = ref(false);
const loadFailedDetail = ref("");

const summary = ref<ListeningSummary | null>(null);
const prevSummary = ref<ListeningSummary | null>(null);
const artists = ref<TopArtist[]>([]);
const tracks = ref<TopTrack[]>([]);
const recent = ref<RecentPlay[]>([]);
const daily = ref<DailyTrend[]>([]);
const hours = ref<PlaysByHour[]>([]);

// Theme (drives Plotly chrome; CSS handles the rest)
const darkQuery = window.matchMedia("(prefers-color-scheme: dark)");
const dark = ref(darkQuery.matches);
const onTheme = (e: MediaQueryListEvent) => (dark.value = e.matches);
onMounted(() => darkQuery.addEventListener("change", onTheme));
onUnmounted(() => darkQuery.removeEventListener("change", onTheme));

/** Current window + the equal-length previous window (for metric deltas). "All" maps to nulls. */
function toRanges(key: RangeKey): { current: Range; previous: Range; isAll: boolean } {
  if (key === "all") {
    return { current: { start: null, end: null }, previous: { start: null, end: null }, isAll: true };
  }
  const days = Number(key);
  const now = new Date();
  const boundary = new Date(now.getTime() - days * 86_400_000);
  const from = new Date(now.getTime() - 2 * days * 86_400_000);
  return {
    current: { start: boundary.toISOString(), end: now.toISOString() },
    previous: { start: from.toISOString(), end: boundary.toISOString() },
    isAll: false,
  };
}

async function loadFromDb(current: Range, previous: Range, isAll: boolean) {
  const [s, ta, tt, rp, dt, pbh] = await Promise.all([
    listeningSummary(current),
    topArtists(current, 10),
    topTracks(current, 10),
    recentPlays(50),
    dailyTrend(current),
    playsByHour(current),
  ]);
  summary.value = s;
  artists.value = ta;
  tracks.value = tt;
  recent.value = rp;
  daily.value = dt;
  hours.value = pbh;
  prevSummary.value = isAll ? null : await listeningSummary(previous);
}

function loadFromSample(current: Range, previous: Range, isAll: boolean) {
  const data = sampleStats(current);
  summary.value = data.summary;
  artists.value = data.topArtists;
  tracks.value = data.topTracks;
  daily.value = data.dailyTrend;
  hours.value = data.playsByHour;
  recent.value = sampleRecentPlays(50);
  prevSummary.value = isAll ? null : sampleStats(previous).summary;
}

async function load() {
  loading.value = true;
  const { current, previous, isAll } = toRanges(range.value);
  try {
    if (isTauri) {
      usingSample.value = false;
      await loadFromDb(current, previous, isAll);
    } else {
      usingSample.value = true;
      loadFromSample(current, previous, isAll);
    }
  } catch (e) {
    console.error("Failed to load dashboard data:", e);
    loadFailedNotice.value = true;
    loadFailedDetail.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}

onMounted(async () => {
  if (isTauri) {
    const result = await syncOnStartup();
    if ("offline" in result) {
      offlineNotice.value = result.reason;
    } else {
      console.log(`Startup sync: inserted ${result.inserted} new play(s).`);
    }
  }
  await load();
});
watch(range, load);

const period = computed(() => {
  if (!summary.value || summary.value.total_plays === 0) return "no data";
  const fmt = (iso: string) => iso.slice(0, 10);
  return `${fmt(summary.value.earliest_played_at!)} ~ ${fmt(summary.value.latest_played_at!)}`;
});

const tiles = computed(() => {
  const cur = summary.value;
  const prev = prevSummary.value;
  const plays = cur?.total_plays ?? 0;
  const mins = cur?.total_mins_played ?? 0;
  const uArtists = cur?.unique_artists ?? 0;
  const uTracks = cur?.unique_tracks ?? 0;
  return [
    { label: "Plays", value: String(plays), d: prev ? delta(plays, prev.total_plays) : null },
    {
      label: "Listening time",
      value: formatMinutes(mins),
      d: prev ? delta(mins, prev.total_mins_played ?? 0) : null,
    },
    {
      label: "Unique artists",
      value: String(uArtists),
      d: prev ? delta(uArtists, prev.unique_artists) : null,
    },
    {
      label: "Unique tracks",
      value: String(uTracks),
      d: prev ? delta(uTracks, prev.unique_tracks) : null,
    },
  ];
});

const hasData = computed(() => (summary.value?.total_plays ?? 0) > 0);

const lastUpdated = computed(() =>
  recent.value.length ? recent.value[0].played_at.replace("T", " ").slice(0, 16) + " UTC" : "—"
);

const seriesColor = computed(() => (dark.value ? "#3987e5" : "#2a78d6"));

const hourTraces = computed(() => {
  const counts = new Array(24).fill(0);
  for (const h of hours.value) counts[h.hour] = h.play_count;
  return [
    {
      type: "bar" as const,
      x: [...Array(24).keys()],
      y: counts,
      marker: { color: seriesColor.value },
      hovertemplate: "%{y} plays<extra></extra>",
    },
  ];
});
const hourLayout = computed(() => ({
  xaxis: { title: { text: "Hour of day (local)" }, dtick: 2 },
  bargap: 0.25, // thin marks with a visible surface gap between bars
}));

const trendTraces = computed(() => [
  {
    type: "scatter" as const,
    mode: "lines" as const,
    x: daily.value.map((d) => d.bucket),
    y: daily.value.map((d) => d.total_mins),
    line: { color: seriesColor.value, width: 2 },
    hovertemplate: "%{y} min<extra></extra>",
  },
]);
</script>

<template>
  <h1>Spotify Listening Dashboard</h1>

  <div class="filters">
    <button
      v-for="r in RANGES"
      :key="r.key"
      class="range-btn"
      :class="{ current: range === r.key }"
      @click="range = r.key"
    >
      {{ r.label }}
    </button>
    <!-- TODO: custom from/to range picker (presets first per dataviz interaction spec) -->
    <span class="period">Period: {{ period }}</span>
  </div>

  <p v-if="usingSample && !loadFailedNotice" class="banner">
    Showing <strong>sample data</strong> — the browser build always shows sample data. Run
    <code>npm run tauri dev</code> for real data from the local cache.
  </p>
  <p v-if="loadFailedNotice" class="banner">
    Could not load real data — showing <strong>sample data</strong> instead. Check the console for
    details.
    <code v-if="loadFailedDetail">{{ loadFailedDetail }}</code>
  </p>
  <p v-if="offlineNotice === 'unconfigured'" class="banner">
    Data not synced — no Worker configured. Set WORKER_URL / WORKER_AUTH_TOKEN in the repo root
    .env and restart the dev server.
  </p>
  <p v-if="offlineNotice === 'error'" class="banner">
    Data not synced (sync failed) — showing last cached data.
  </p>

  <div :class="{ loading }">
    <div class="metrics">
      <div v-for="t in tiles" :key="t.label" class="metric">
        <div class="label">{{ t.label }}</div>
        <div class="value">{{ t.value }}</div>
        <div v-if="t.d !== null" class="delta" :class="t.d >= 0 ? 'up' : 'down'">
          {{ t.d >= 0 ? "↑" : "↓" }} {{ Math.abs(t.d).toFixed(1) }}% vs previous period
        </div>
        <div v-else class="delta">—</div>
      </div>
    </div>

    <div class="cols">
      <div class="card">
        <h3>Top Artists — by listening time</h3>
        <table>
          <thead><tr><th>Artist</th><th class="num">Listening time</th></tr></thead>
          <!-- TODO: add a slider (constraint the box max height), max shown up to 20 -->
          <tbody>
            <tr v-for="a in artists" :key="a.artist_name">
              <td>{{ a.artist_name }}</td>
              <td class="num">{{ formatMinutes(a.total_mins) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="card">
        <h3>Top Tracks — by play count</h3>
        <table>
          <!-- TODO: add a slider (constraint the box max height), max shown up to 20 -->
          <thead><tr><th>Track</th><th>Artist</th><th class="num">Plays</th><th>Spotify</th></tr></thead>
          <tbody>
            <tr v-for="t in tracks" :key="t.track_id">
              <td>{{ t.track_name }}</td>
              <td>{{ t.artist_name }}</td>
              <td class="num">{{ t.play_count }}</td>
              <td><a :href="spotifyUrl(t.track_id)" target="_blank" rel="noopener">Open</a></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div class="card">
      <h3>Daily Activity Pattern</h3>
      <!-- TODO: 1. add a button at the top-right has two options: play count and hour plays -->
      <!-- TODO: 2. if change to "hour plays", the chart will display hourly play counts (also hover_template)-->
      <PlotChart v-if="hasData" :traces="hourTraces" :layout="hourLayout" :dark="dark" />
      <p v-else>No data in this period.</p>
    </div>
    
    <div class="card">
      <h3>Listening Trend</h3>
      <!-- TODO: 1. add a button at the top-right has two options: play count and hour plays -->
      <!-- TODO: 2. if change to "hour plays", the chart will display hourly play counts (also hover_template)-->
      <!-- TODO: 3. add extra options can change the granularity of x axis: day/week/month -->
      <PlotChart v-if="hasData" :traces="trendTraces" :dark="dark" />
      <p v-else>No data in this period.</p>
    </div>

    <div class="card">
      <h3>Generate Report</h3>
      <!-- Wired later: Tauri command -> spawn-per-call Python report engine (spec §4.5/§5) -->
      <button class="range-btn" disabled>Generate weekly report (coming soon)</button>
    </div>

    <details class="card">
      <summary>Recently Played</summary>
      <div class="recent-table-scroll">
        <table>
          <thead>
            <tr><th>Played at (UTC)</th><th>Track</th><th>Artist</th><th>Album</th><th>Spotify</th></tr>
          </thead>
          <tbody>
            <tr v-for="r in recent" :key="`${r.track_id}-${r.played_at}`">
              <td>{{ r.played_at.replace("T", " ").slice(0, 19) }}</td>
              <td>{{ r.track_name }}</td>
              <td>{{ r.artist_name }}</td>
              <td>{{ r.album_name }}</td>
              <td><a :href="spotifyUrl(r.track_id)" target="_blank" rel="noopener">Open</a></td>
            </tr>
          </tbody>
        </table>
      </div>
    </details>
  </div>

  <footer>Last played {{ lastUpdated }}</footer>
</template>
