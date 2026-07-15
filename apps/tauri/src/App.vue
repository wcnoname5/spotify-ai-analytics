<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import PlotChart from "./components/PlotChart.vue";
import { fetchTracks, sampleTracks, type TrackRow } from "./lib/api";
import {
  delta,
  formatMinutes,
  metrics,
  minutesByDay,
  playsByHour,
  spotifyUrl,
  topArtistsByTime,
  topTracksByPlays,
} from "./lib/stats";

type RangeKey = "7" | "30" | "90" | "all";
const RANGES: { key: RangeKey; label: string }[] = [
  { key: "7", label: "7 days" },
  { key: "30", label: "30 days" },
  { key: "90", label: "90 days" },
  { key: "all", label: "All time" },
];

const range = ref<RangeKey>("30");
const rows = ref<TrackRow[]>([]); // current window
const prevRows = ref<TrackRow[]>([]); // previous window of equal length (for deltas)
const loading = ref(false);
const usingSample = ref(false);

// Theme (drives Plotly chrome; CSS handles the rest)
const darkQuery = window.matchMedia("(prefers-color-scheme: dark)");
const dark = ref(darkQuery.matches);
const onTheme = (e: MediaQueryListEvent) => (dark.value = e.matches);
onMounted(() => darkQuery.addEventListener("change", onTheme));
onUnmounted(() => darkQuery.removeEventListener("change", onTheme));

const EPOCH = "2008-01-01T00:00:00Z"; // before Spotify existed — "all time"

async function load() {
  loading.value = true;
  const now = new Date();
  const days = range.value === "all" ? null : Number(range.value);
  // One request covers current + previous window; split client-side.
  const fromIso = days ? new Date(now.getTime() - 2 * days * 86_400_000).toISOString() : EPOCH;
  const boundaryIso = days ? new Date(now.getTime() - days * 86_400_000).toISOString() : EPOCH;
  try {
    let all: TrackRow[];
    try {
      all = await fetchTracks(fromIso, now.toISOString());
      usingSample.value = false;
    } catch {
      all = sampleTracks(fromIso, now.toISOString());
      usingSample.value = true;
    }
    rows.value = all.filter((r) => r.played_at >= boundaryIso);
    prevRows.value = days ? all.filter((r) => r.played_at < boundaryIso) : [];
  } finally {
    loading.value = false;
  }
}
onMounted(load);
watch(range, load);

const period = computed(() => {
  if (rows.value.length === 0) return "no data";
  const fmt = (iso: string) => iso.slice(0, 10);
  return `${fmt(rows.value[0].played_at)} ~ ${fmt(rows.value[rows.value.length - 1].played_at)}`;
});

const current = computed(() => metrics(rows.value));
const previous = computed(() => metrics(prevRows.value));
const tiles = computed(() => [
  { label: "Plays", value: String(current.value.plays), d: delta(current.value.plays, previous.value.plays) },
  {
    label: "Listening time",
    value: formatMinutes(current.value.minutes),
    d: delta(current.value.minutes, previous.value.minutes),
  },
  {
    label: "Unique artists",
    value: String(current.value.uniqueArtists),
    d: delta(current.value.uniqueArtists, previous.value.uniqueArtists),
  },
  {
    label: "Unique tracks",
    value: String(current.value.uniqueTracks),
    d: delta(current.value.uniqueTracks, previous.value.uniqueTracks),
  },
]);

const topArtists = computed(() => topArtistsByTime(rows.value));
const topTracks = computed(() => topTracksByPlays(rows.value));
const recent = computed(() =>
  [...rows.value].sort((a, b) => b.played_at.localeCompare(a.played_at)).slice(0, 50)
);
const lastUpdated = computed(() =>
  rows.value.length ? recent.value[0].played_at.replace("T", " ").slice(0, 16) + " UTC" : "—"
);

const seriesColor = computed(() => (dark.value ? "#3987e5" : "#2a78d6"));

const hourTraces = computed(() => [
  {
    type: "bar" as const,
    x: [...Array(24).keys()],
    y: playsByHour(rows.value),
    marker: { color: seriesColor.value },
    hovertemplate: "%{y} plays<extra></extra>",
  },
]);
const hourLayout = computed(() => ({
  xaxis: { title: { text: "Hour of day (local)" }, dtick: 2 },
  bargap: 0.25, // thin marks with a visible surface gap between bars
}));

const trendTraces = computed(() => {
  const daily = minutesByDay(rows.value);
  return [
    {
      type: "scatter" as const,
      mode: "lines" as const,
      x: daily.map((d) => d.day),
      y: daily.map((d) => d.minutes),
      line: { color: seriesColor.value, width: 2 },
      hovertemplate: "%{y} min<extra></extra>",
    },
  ];
});
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

  <p v-if="usingSample" class="banner">
    Showing <strong>sample data</strong> — no Worker configured. Set WORKER_URL / WORKER_AUTH_TOKEN
    in the repo root .env and restart the dev server.
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
          <tbody>
            <tr v-for="a in topArtists" :key="a.artist">
              <td>{{ a.artist }}</td>
              <td class="num">{{ formatMinutes(a.minutes) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="card">
        <h3>Top Tracks — by play count</h3>
        <table>
          <thead><tr><th>Track</th><th>Artist</th><th class="num">Plays</th><th>Spotify</th></tr></thead>
          <tbody>
            <tr v-for="t in topTracks" :key="t.trackId">
              <td>{{ t.track }}</td>
              <td>{{ t.artist }}</td>
              <td class="num">{{ t.plays }}</td>
              <td><a :href="spotifyUrl(t.trackId)" target="_blank" rel="noopener">Open</a></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div class="card">
      <h3>Daily Activity Pattern</h3>
      <PlotChart v-if="rows.length" :traces="hourTraces" :layout="hourLayout" :dark="dark" />
      <p v-else>No data in this period.</p>
    </div>

    <div class="card">
      <h3>Listening Trend</h3>
      <PlotChart v-if="rows.length" :traces="trendTraces" :dark="dark" />
      <p v-else>No data in this period.</p>
    </div>

    <div class="card">
      <h3>Generate Report</h3>
      <!-- Wired later: Tauri command -> spawn-per-call Python report engine (spec §4.5/§5) -->
      <button class="range-btn" disabled>Generate weekly report (coming soon)</button>
    </div>

    <details class="card">
      <summary>Recently Played (last 50)</summary>
      <table>
        <thead>
          <tr><th>Played at (UTC)</th><th>Track</th><th>Artist</th><th>Album</th><th>Spotify</th></tr>
        </thead>
        <tbody>
          <tr v-for="r in recent" :key="r.id">
            <td>{{ r.played_at.replace("T", " ").slice(0, 19) }}</td>
            <td>{{ r.track_name }}</td>
            <td>{{ r.artist_name }}</td>
            <td>{{ r.album_name }}</td>
            <td><a :href="spotifyUrl(r.track_id)" target="_blank" rel="noopener">Open</a></td>
          </tr>
        </tbody>
      </table>
    </details>
  </div>

  <footer>Last played {{ lastUpdated }}</footer>
</template>
