<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import PlotChart from "./components/PlotChart.vue";
import ReportPage from "./ReportPage.vue";
import { getConfig } from "./lib/config";
import { sampleRecentPlays, sampleStats } from "./lib/api";
import { isTauri } from "./lib/db";
import { syncOnStartup, syncReports } from "./lib/sync";
import {
  trend,
  dataRange,
  listeningSummary,
  playsByHour,
  recentPlays,
  topArtists,
  topTracks,
  type TrendPoint,
  type Granularity,
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

const page = ref<"dashboard" | "report">("dashboard");

/** Setup now lives in its own window (Rust get-or-creates it). */
const openSetup = () => invoke("open_setup_window").catch(console.error);

/** Which .env this session resolved to — empty unless it is a non-default one. */
const envBadge = ref("");

// The main window starts hidden. An unconfigured environment shows only the
// Setup window; a configured one reveals the dashboard. 
// Fail-soft: on error show the dashboard, never leave the user with no window.
onMounted(async () => {
  if (!isTauri) return;
  let configured = true;
  try {
    const cfg = await getConfig();
    configured = cfg.configured.client_id;
    if (cfg.dev) envBadge.value = `DEV · ${cfg.env_file}`;
  } catch (e) {
    console.error("first-run check failed:", e);
  }
  invoke("main_ready", { configured }).catch(console.error);
  // Settings apply on restart and this window's config memo went stale while
  // Setup was open; a reload is the whole refresh.
  listen("setup-done", () => location.reload());
});
const range = ref<RangeKey | "custom">("30");
const customStart = ref(""); // YYYY-MM-DD, "" = unset
const customEnd = ref("");
const minDate = ref(""); // earliest played_at date, set on mount (Tauri only)
const today = new Date();
const todayStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
const maxDate = ref(todayStr); // latest played_at date, set on mount (Tauri only)
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
const daily = ref<TrendPoint[]>([]);
const hours = ref<PlaysByHour[]>([]);
const trendGranularity = ref<Granularity>("day");

// Theme (drives Plotly chrome; CSS handles the rest)
const darkQuery = window.matchMedia("(prefers-color-scheme: dark)");
const dark = ref(darkQuery.matches);
const onTheme = (e: MediaQueryListEvent) => (dark.value = e.matches);
onMounted(() => darkQuery.addEventListener("change", onTheme));
onUnmounted(() => darkQuery.removeEventListener("change", onTheme));

/** Days spanned by the current range; Infinity for "all" / open-ended custom. */
const rangeDays = computed(() => {
  const { current } = toRanges(range.value);
  if (!current.start || !current.end) return Infinity;
  return (Date.parse(current.end) - Date.parse(current.start)) / 86_400_000;
});

function granularityDisabled(g: Granularity) {
  if (g === "week") return rangeDays.value < 7 * 3;
  if (g === "month") return rangeDays.value < 30 * 3;
  return false;
}
// Range shrank past the active granularity's threshold: fall back to "day".
watch(rangeDays, () => {
  if (granularityDisabled(trendGranularity.value)) trendGranularity.value = "day";
});

function setPreset(k: RangeKey) {
  customStart.value = "";
  customEnd.value = "";
  range.value = k;
}

/** Current window + the equal-length previous window (for metric deltas). "All" maps to nulls. */
function toRanges(key: RangeKey | "custom"): { current: Range; previous: Range; isAll: boolean } {
  if (key === "custom") {
    const start = customStart.value ? new Date(customStart.value + "T00:00:00").toISOString() : null;
    const end = customEnd.value ? new Date(customEnd.value + "T23:59:59.999").toISOString() : null;
    if (start && end) {
      const len = Date.parse(end) - Date.parse(start);
      const prevStart = new Date(Date.parse(start) - len).toISOString();
      return { current: { start, end }, previous: { start: prevStart, end: start }, isAll: false };
    }
    // Open-ended range: no defined "previous", deltas hide (isAll behavior).
    return { current: { start, end }, previous: { start: null, end: null }, isAll: true };
  }
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
    topArtists(current, 20),
    topTracks(current, 20),
    recentPlays(50, current.start, current.end), // TODO: support custom range for recent plays (currently only the last 50 plays, regardless of range)
    trend(current, trendGranularity.value),
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
  const data = sampleStats(current, 20, trendGranularity.value);
  summary.value = data.summary;
  artists.value = data.topArtists;
  tracks.value = data.topTracks;
  daily.value = data.dailyTrend;
  hours.value = data.playsByHour;
  recent.value = sampleRecentPlays(50);
  prevSummary.value = isAll ? null : sampleStats(previous, 20, trendGranularity.value).summary;
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

async function refreshTrend() {
  const { current } = toRanges(range.value);
  daily.value = usingSample.value
    ? sampleStats(current, 20, trendGranularity.value).dailyTrend
    : await trend(current, trendGranularity.value);
}

onMounted(async () => {
  if (isTauri) {
    const dr = await dataRange();
    if (dr.earliest) minDate.value = dr.earliest.slice(0, 10);
    if (dr.latest) maxDate.value = dr.latest.slice(0, 10);
    const result = await syncOnStartup();
    if ("offline" in result) {
      offlineNotice.value = result.reason;
    } else {
      console.log(`Startup sync: inserted ${result.inserted} new play(s).`);
    }
    syncReports().catch(console.error);
  }
  await load();
});
watch(range, load);
// Editing either date switches to custom and reloads.
watch([customStart, customEnd], () => {
  if (!customStart.value && !customEnd.value) return;
  if (range.value === "custom") load();
  else range.value = "custom"; // watch(range, load) fires the load
});
watch(trendGranularity, refreshTrend);

const period = computed(() => {
  if (range.value === "7" || range.value === "30" || range.value === "90") {
    const { current } = toRanges(range.value);
    return `${current.start!.slice(0, 10)} ~ ${current.end!.slice(0, 10)}`;
  }
  // Custom: falls back to the all data range (minDate/maxDate) when a side is unset.
  if (range.value === "custom") {
    const start = customStart.value || minDate.value || "?";
    const end = customEnd.value || maxDate.value;
    return `${start} ~ ${end}`;
  }
  // range.value === "all"
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

const seriesColor = computed(() => (dark.value ? "#3987e5" : "#2a78d6"));

const hourTraces = computed(() => {
  const y = new Array(24).fill(0);
  const mins = new Array(24).fill(0);
  for (const h of hours.value) {
    y[h.hour] = h.play_count;
    mins[h.hour] = h.total_mins ?? 0;
  }
  return [
    {
      type: "bar" as const,
      x: [...Array(24).keys()],
      y,
      customdata: mins,
      marker: { color: seriesColor.value },
      hovertemplate: "%{y} plays · %{customdata} min<extra></extra>",
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
    customdata: daily.value.map((d) => d.play_count),
    line: { color: seriesColor.value, width: 2 },
    hovertemplate: "%{y} min · %{customdata} plays<extra></extra>",
  },
]);
</script>

<template>
  <header class="app-head">
    <h1>Spotify Listening Analysis</h1>
    <span v-if="envBadge" class="env-badge" :title="envBadge">{{ envBadge }}</span>
    <button v-if="isTauri" class="btn gear" title="Setup" aria-label="Setup" @click="openSetup">⚙</button>
  </header>

  <nav class="filters">
    <button class="btn nav-btn" :class="{ current: page === 'dashboard' }" @click="page = 'dashboard'">Dashboard</button>
    <button class="btn nav-btn" :class="{ current: page === 'report' }" @click="page = 'report'">Report</button>
  </nav>
  <hr class="nav-divider" />

  <div v-show="page === 'dashboard'">
  <div class="filters">
    <button
      v-for="r in RANGES"
      :key="r.key"
      class="btn"
      :class="{ current: range === r.key }"
      @click="setPreset(r.key)"
    >
      {{ r.label }}
    </button>
    <span class="period">Period: {{ period }}</span>
    <div class="custom-range filters">
      <button class="btn" :class="{ current: range === 'custom' }" @click="range = 'custom'">
        Custom
      </button>
      <input type="date" v-model="customStart" :min="minDate || undefined" :max="customEnd || maxDate" />
      <span>–</span>
      <input type="date" v-model="customEnd" :min="customStart || minDate || undefined" :max="maxDate" />
    </div>
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
        <div class="table-scroll">
          <table>
            <thead><tr><th>Artist</th><th class="num">Listening time</th></tr></thead>
            <tbody>
              <tr v-for="a in artists" :key="a.artist_name">
                <td>{{ a.artist_name }}</td>
                <td class="num">{{ formatMinutes(a.total_mins) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
      <div class="card">
        <h3>Top Tracks — by play count</h3>
        <div class="table-scroll">
          <table>
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
    </div>

    <div class="card">
      <h3>Daily Activity Pattern</h3>
      <PlotChart v-if="hasData" :traces="hourTraces" :layout="hourLayout" :dark="dark" />
      <p v-else>No data in this period.</p>
    </div>
    
    <div class="card">
      <div class="card-head">
        <h3>Listening Trend</h3>
        <div>
          <button v-for="g in (['day', 'week', 'month'] as const)" :key="g" class="btn"
            :disabled="granularityDisabled(g)"
            :class="{ current: trendGranularity === g }" @click="trendGranularity = g">{{ g }}</button>
        </div>
      </div>
      <PlotChart v-if="hasData" :traces="trendTraces" :dark="dark" />
      <p v-else>No data in this period.</p>
    </div>

    <details class="card">
      <summary>Recently Played</summary>
      <div class="table-scroll">
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
  </div>

  <ReportPage v-show="page === 'report'" />


</template>

<style scoped>
.app-head { display: flex; align-items: center; justify-content: space-between; gap: 1rem; }
.gear { font-size: 1.15rem; line-height: 1; padding: 0.3rem 0.55rem; }
/* Which .env this session resolved to — the twin-.env question, answered on screen. */
.env-badge {
  margin-right: auto; font-size: 0.7rem; font-family: monospace; color: var(--muted);
  border: 1px solid var(--border); border-radius: 999px; padding: 0.15rem 0.5rem;
  max-width: 28rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
</style>
