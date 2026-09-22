<script setup lang="ts">
// Gantt of 7 days of listening, then a year of daily minutes as a GitHub-style calendar.
// Chart configs live in lib/gantt.ts and lib/heatmap.ts, testable outside the app.
import { computed, onMounted, ref, watch } from "vue";
import PlotChart from "./components/PlotChart.vue";
import { isTauri } from "./lib/db";
import {
  buildGantt,
  dayEndIso,
  dayStartIso,
  ganttLayout,
  ganttTraces,
  localDay,
  windowDays,
  type TimelinePlay,
} from "./lib/gantt";
import { heatmapWeeks, yearSpan, type Cell } from "./lib/heatmap";
import { dataRange, listeningTimeline, trend, type TrendPoint } from "./lib/queries";

const props = defineProps<{ dark: boolean }>();

const plays = ref<TimelinePlay[]>([]);
const daily = ref<TrendPoint[]>([]);
const earliest = ref<Date | null>(null);
const latest = ref<Date | null>(null);
/** Filters: the Gantt's last day (it shows the 7 days ending there), and a year
 *  ("" = last 12 months) for the heatmap. */
const endDay = ref("");
const year = ref("");
const loading = ref(true);
const error = ref("");

const days = computed(() => (endDay.value ? windowDays(new Date(endDay.value + "T00:00:00"), 7) : []));
const span = computed(() => (latest.value ? yearSpan(year.value, latest.value) : null));
const years = computed(() => {
  if (!earliest.value || !latest.value) return [];
  const out: number[] = [];
  for (let y = latest.value.getFullYear(); y >= earliest.value.getFullYear(); y--) out.push(y);
  return out;
});

const fail = (e: unknown) => (error.value = e instanceof Error ? e.message : String(e));

onMounted(async () => {
  if (!isTauri) {
    loading.value = false;
    return;
  }
  try {
    // Defaults anchor on the newest play, not on today: the dashboard's presets
    // run off `new Date()`, which shows nothing when the cache is a few weeks stale.
    const range = await dataRange();
    if (!range.latest || !range.earliest) return;
    earliest.value = new Date(range.earliest);
    latest.value = new Date(range.latest);
    endDay.value = localDay(latest.value); // fires the days watcher below
  } catch (e) {
    fail(e);
  } finally {
    loading.value = false;
  }
});

// ponytail: no request sequencing — a slow query for an old filter value could
// land after a newer one. Local SQLite answers in ms; add a counter if it bites.
watch(days, (d) => {
  if (d.length) listeningTimeline({ start: dayStartIso(d[0]), end: dayEndIso(d[6]) }).then((p) => (plays.value = p), fail);
});
watch(span, (s) => {
  if (s) trend({ start: dayStartIso(s[0]), end: dayEndIso(s[1]) }, "day").then((r) => (daily.value = r), fail);
});

const theme = computed(() => (props.dark ? "dark" : "light") as "dark" | "light");
const gantt = computed(() => buildGantt(plays.value, days.value));
const traces = computed(() => ganttTraces(gantt.value, theme.value));
const layout = computed(() => ganttLayout(gantt.value, theme.value));
const hasData = computed(() => gantt.value.bars.length > 0);

const weeks = computed(() => (span.value ? heatmapWeeks(daily.value, ...span.value) : []));
/** A month label over the first column whose Sunday falls in a new month. */
const monthLabels = computed(() =>
  weeks.value.map((col, i) => {
    const m = col[0]?.day.slice(5, 7);
    return i > 0 && m !== weeks.value[i - 1][0]?.day.slice(5, 7)
      ? new Date(col[0]!.day + "T00:00").toLocaleString(undefined, { month: "short" })
      : "";
  })
);
/** The hovered cell plus where to draw its tooltip (viewport coords, so the
 *  horizontally scrolling calendar can't clip it). */
const tip = ref<{ cell: Cell; x: number; y: number } | null>(null);
const showTip = (cell: Cell, e: MouseEvent) => {
  const r = (e.target as HTMLElement).getBoundingClientRect();
  tip.value = { cell, x: r.left + r.width / 2, y: r.top };
};
const cellBg = (level: number) =>
  level === 0 ? "var(--grid)" : `color-mix(in srgb, var(--series) ${level * 25}%, var(--grid))`;
</script>

<template>
  <div class="card">
    <div class="card-head">
      <h3>Listening Timeline</h3>
      <!-- v-if on latest, not days: clearing the input must not hide the input. -->
      <span v-if="latest" class="filters">
        <span v-if="days.length" class="range">{{ days[0] }} → {{ days[6] }}</span>
        <input
          type="date"
          v-model="endDay"
          :min="earliest ? localDay(earliest) : undefined"
          :max="localDay(latest)"
          required
        />
      </span>
    </div>

    <p v-if="!isTauri">The timeline reads the local database — run it in the app.</p>
    <p v-else-if="loading">Loading…</p>
    <p v-else-if="error" class="err">Failed to load the timeline: {{ error }}</p>
    <p v-else-if="!hasData">No plays in these 7 days.</p>

    <template v-else>
      <PlotChart
        :traces="traces"
        :layout="layout"
        :dark="dark"
        :style="{ height: layout.height + 'px' }"
      />
      <p class="hint">Drag to zoom · double-click to reset</p>
    </template>
  </div>

  <div v-if="span" class="card">
    <div class="card-head">
      <h3>Daily Activity</h3>
      <span class="filters">
        <span class="range">{{ span[0] }} → {{ span[1] }}</span>
        <select v-model="year">
          <option value="">Last 12 months</option>
          <option v-for="y in years" :key="y" :value="String(y)">{{ y }}</option>
        </select>
      </span>
    </div>
    <div class="cal-scroll">
      <div class="cal" :style="{ '--weeks': weeks.length }" @mouseleave="tip = null">
        <span v-for="(m, i) in monthLabels" :key="'m' + i" class="month" :style="{ gridColumn: i + 2 }">{{ m }}</span>
        <span v-for="(d, i) in ['', 'Mon', '', 'Wed', '', 'Fri', '']" :key="'d' + i" class="dow" :style="{ gridRow: i + 2 }">{{ d }}</span>
        <template v-for="(col, w) in weeks" :key="w">
          <span
            v-for="(c, d) in col"
            :key="d"
            class="cell"
            :style="{ gridColumn: w + 2, gridRow: d + 2, background: c ? cellBg(c.level) : 'transparent' }"
            @mouseenter="c ? showTip(c, $event) : (tip = null)"
          ></span>
        </template>
      </div>
    </div>
    <div v-if="tip" class="tip" :style="{ left: tip.x + 'px', top: tip.y + 'px' }">
      <b>{{ (tip.cell.mins).toFixed(0) }} m</b> · {{ tip.cell.day }}
    </div>
  </div>
</template>

<style scoped>
.range { font-size: 0.8rem; color: var(--muted); }
.err { color: var(--down); }
.card-head .filters { margin-bottom: 0; }
.hint { margin: 0.25rem 0 0; font-size: 0.75rem; color: var(--muted); text-align: right; }
.cal-scroll { overflow-x: auto; }
.cal {
  display: grid; gap: 3px; width: max-content;
  grid-template-columns: 2rem repeat(var(--weeks), 11px);
  grid-template-rows: 1rem repeat(7, 11px);
  font-size: 0.7rem; color: var(--muted);
}
.month { grid-row: 1; white-space: nowrap; }
.dow { grid-column: 1; line-height: 11px; }
.cell { border-radius: 2px; }
/* Matches PlotChart's hoverlabel so both charts' hovers look alike. */
.tip {
  position: fixed; transform: translate(-50%, calc(-100% - 6px)); pointer-events: none;
  background: var(--surface); border: 1px solid var(--border); border-radius: 4px;
  padding: 0.2rem 0.45rem; font-size: 0.75rem; color: var(--ink); white-space: nowrap;
}
</style>
