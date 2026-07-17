# Dashboard TODOs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the four App.vue TODO clusters: custom date range with min/max validation, scrollable 20-row top tables, metric toggle on both charts, day/week/month granularity on the trend chart.

**Architecture:** All frontend (`apps/tauri/src/`) except one shared SQL edit (`plays_by_hour.sql` gains `total_mins`). Trend granularity reuses the already-existing `trend_weekly.sql` / `trend_monthly.sql`. Worker stays frozen.

**Tech Stack:** Vue 3 `<script setup>`, tauri-plugin-sql, Plotly (via existing `PlotChart.vue`), shared `.sql` files under `packages/core/spotify_core/db/sql/`.

**Spec:** `docs/superpowers/specs/2026-07-18-dashboard-todos-design.md`

## Global Constraints

- No Worker/D1 changes; no new dependencies; no new Vue components.
- SQL param convention: `?1`=start, `?2`=end, `?3`=tz modifier, trailing params after.
- Verification per task: `npx vue-tsc --noEmit` in `apps/tauri` passes, then commit.
- No frontend test runner exists (deliberate); checks are typecheck + `uv run pytest` (shared SQL) + final visual pass in `npm run tauri dev`.
- The branch has uncommitted WIP (App.vue, styles.css, stats.ts→formatters.ts rename). **Task 0 commits it first** so each task's diff is clean.

---

### Task 0: Commit pending WIP

**Files:** none new — commits the existing working-tree state.

- [ ] **Step 1: Typecheck the WIP as-is**

Run: `cd apps/tauri && npx vue-tsc --noEmit`
Expected: no errors.

- [ ] **Step 2: Commit**

```bash
git add -A apps/tauri
git commit -m "WIP: frontend — formatters rename, App.vue TODO markers"
```

---

### Task 1: Custom date range picker with min/max validation

**Files:**
- Modify: `apps/tauri/src/lib/queries.ts` (add `dataRange()`)
- Modify: `apps/tauri/src/App.vue` (range state, `toRanges`, template)
- Modify: `apps/tauri/src/styles.css` (date input styling)

**Interfaces:**
- Consumes: existing `Range`, `getDb()`, `data_range.sql`.
- Produces: `dataRange(): Promise<DataRange>` with `DataRange { earliest: string | null; latest: string | null }`; App.vue range state widened to `RangeKey | "custom"` (Tasks 3–4 read `toRanges(range.value).current`).

- [ ] **Step 1: Add `dataRange()` to queries.ts**

```ts
import dataRangeSql from "@sql/data_range.sql?raw";

export interface DataRange {
  earliest: string | null;
  latest: string | null;
}

/** Global min/max played_at — drives the date inputs' min/max validation. */
export async function dataRange(): Promise<DataRange> {
  const db = await getDb();
  const rows = await db.select<DataRange[]>(dataRangeSql, []);
  return rows[0];
}
```

- [ ] **Step 2: Widen range state and `toRanges` in App.vue**

```ts
const range = ref<RangeKey | "custom">("30");
const customStart = ref(""); // YYYY-MM-DD, "" = unset
const customEnd = ref("");
const minDate = ref(""); // earliest played_at date, set on mount (Tauri only)
const today = new Date();
const maxDate = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;

function setPreset(k: RangeKey) {
  customStart.value = "";
  customEnd.value = "";
  range.value = k;
}
// Editing either date switches to custom and reloads.
watch([customStart, customEnd], () => {
  if (!customStart.value && !customEnd.value) return;
  if (range.value === "custom") load();
  else range.value = "custom"; // watch(range, load) fires the load
});
```

`toRanges` gains a custom branch (note: `"T00:00:00"` without `Z` parses as **local** time, which is what we want):

```ts
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
  if (key === "all") { /* unchanged */ }
  /* preset branch unchanged */
}
```

In `onMounted` (Tauri branch, before `load()`):

```ts
const dr = await dataRange();
if (dr.earliest) minDate.value = dr.earliest.slice(0, 10);
```

- [ ] **Step 3: Template — presets call `setPreset`, add date inputs**

Replace `@click="range = r.key"` with `@click="setPreset(r.key)"`, and replace the picker TODO comment with:

```html
<input type="date" v-model="customStart" :min="minDate || undefined" :max="customEnd || maxDate" />
<span>–</span>
<input type="date" v-model="customEnd" :min="customStart || minDate || undefined" :max="maxDate" />
```

- [ ] **Step 4: Style the date inputs in styles.css**

```css
.filters input[type="date"] {
  font: inherit;
  font-size: 0.85rem;
  padding: 0.3rem 0.5rem;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface);
  color: var(--ink-2);
}
```

- [ ] **Step 5: Typecheck**

Run: `cd apps/tauri && npx vue-tsc --noEmit`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add apps/tauri/src
git commit -m "feat(tauri): custom date range picker with min/max validation"
```

---

### Task 2: Top Artists / Top Tracks — 20 rows in a scroll box

**Files:**
- Modify: `apps/tauri/src/App.vue` (limits, scroll wrappers)
- Modify: `apps/tauri/src/styles.css` (generalize scroll class, sticky header)

**Interfaces:**
- Consumes: existing `topArtists` / `topTracks` / `sampleStats(range, limit)`.
- Produces: `.table-scroll` CSS class (replaces `.recent-table-scroll`; Recently Played updated too).

- [ ] **Step 1: Bump limits in App.vue**

In `loadFromDb`: `topArtists(current, 20)`, `topTracks(current, 20)`.
In `loadFromSample`: `sampleStats(current, 20)` and `sampleStats(previous, 20).summary`.

- [ ] **Step 2: Generalize the scroll class**

In `styles.css`, rename `.recent-table-scroll` → `.table-scroll` and add a sticky header:

```css
.table-scroll {
  max-height: 24rem;
  overflow-y: auto;
}
.table-scroll thead th {
  position: sticky;
  top: 0;
  background: var(--surface);
}
```

In App.vue: rename the Recently Played wrapper `class="recent-table-scroll"` → `class="table-scroll"`, and wrap both top-card `<table>`s in `<div class="table-scroll">…</div>` (remove the slider TODO comments).

- [ ] **Step 3: Typecheck**

Run: `cd apps/tauri && npx vue-tsc --noEmit`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add apps/tauri/src
git commit -m "feat(tauri): top artists/tracks show 20 rows in a sticky-header scroll box"
```

---

### Task 3: Daily Activity Pattern — Plays / Listening time toggle

**Files:**
- Modify: `packages/core/spotify_core/db/sql/plays_by_hour.sql` (add `total_mins`)
- Modify: `apps/tauri/src/lib/queries.ts` (`PlaysByHour` interface)
- Modify: `apps/tauri/src/lib/api.ts` (sample mins per hour)
- Modify: `apps/tauri/src/App.vue` (toggle + traces)
- Modify: `apps/tauri/src/styles.css` (card header row, unscope `.range-btn`)

**Interfaces:**
- Consumes: `plays_by_hour.sql` params `?1/?2/?3` (unchanged).
- Produces: `PlaysByHour { hour: number; play_count: number; total_mins: number }`; `.card-head` CSS class and unscoped `.range-btn` (Task 4 reuses both).

- [ ] **Step 1: Add `total_mins` to plays_by_hour.sql**

```sql
SELECT CAST(strftime('%H', datetime(played_at, ?3)) AS INTEGER) AS hour,
       COUNT(*) AS play_count,
       SUM(ms_played) / 60000 AS total_mins
FROM listening_history
WHERE (?1 IS NULL OR played_at >= ?1)
  AND (?2 IS NULL OR played_at <= ?2)
GROUP BY hour
ORDER BY hour
```

- [ ] **Step 2: Run pytest (shared SQL sanity — no Python caller expected)**

Run: `uv run pytest`
Expected: all green (219+).

- [ ] **Step 3: Update `PlaysByHour` in queries.ts**

```ts
export interface PlaysByHour {
  hour: number;
  play_count: number;
  total_mins: number;
}
```

- [ ] **Step 4: Sample data — mins per hour in api.ts**

Replace the `hourCounts` block in `sampleStats`:

```ts
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
```

- [ ] **Step 5: Toggle state + traces in App.vue**

```ts
const hourMetric = ref<"plays" | "mins">("plays");

const hourTraces = computed(() => {
  const y = new Array(24).fill(0);
  for (const h of hours.value) y[h.hour] = hourMetric.value === "plays" ? h.play_count : h.total_mins;
  return [
    {
      type: "bar" as const,
      x: [...Array(24).keys()],
      y,
      marker: { color: seriesColor.value },
      hovertemplate:
        hourMetric.value === "plays" ? "%{y} plays<extra></extra>" : "%{y} min<extra></extra>",
    },
  ];
});
```

Card template (replaces the two TODO comments):

```html
<div class="card-head">
  <h3>Daily Activity Pattern</h3>
  <div>
    <button class="range-btn" :class="{ current: hourMetric === 'plays' }" @click="hourMetric = 'plays'">Plays</button>
    <button class="range-btn" :class="{ current: hourMetric === 'mins' }" @click="hourMetric = 'mins'">Listening time</button>
  </div>
</div>
```

- [ ] **Step 6: CSS — unscope `.range-btn`, add `.card-head`**

In `styles.css`, change the three `.filters .range-btn…` selectors to plain `.range-btn`, `.range-btn:hover`, `.range-btn.current` (they render identically in the filter row), and add:

```css
.card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 0.5rem;
}
.card-head .range-btn {
  font-size: 0.8rem;
  padding: 0.2rem 0.6rem;
}
```

- [ ] **Step 7: Typecheck**

Run: `cd apps/tauri && npx vue-tsc --noEmit`
Expected: no errors.

- [ ] **Step 8: Commit**

```bash
git add apps/tauri/src packages/core/spotify_core/db/sql/plays_by_hour.sql
git commit -m "feat: activity-pattern chart toggles plays vs listening time (plays_by_hour.sql gains total_mins)"
```

---

### Task 4: Listening Trend — metric toggle + day/week/month granularity

**Files:**
- Modify: `apps/tauri/src/lib/queries.ts` (`trend()` replaces `dailyTrend()`, `TrendPoint` renames `DailyTrend`)
- Modify: `apps/tauri/src/lib/api.ts` (granularity-aware sample bucketing)
- Modify: `apps/tauri/src/App.vue` (toggles, traces, trend-only refresh)

**Interfaces:**
- Consumes: `trend_daily.sql` / `trend_weekly.sql` / `trend_monthly.sql` (all exist; weekly buckets = ISO-Monday date, monthly = `YYYY-MM`); `.card-head` + `.range-btn` from Task 3.
- Produces: `type Granularity = "day" | "week" | "month"`; `trend(range: Range, granularity: Granularity): Promise<TrendPoint[]>`; `TrendPoint { bucket: string; total_mins: number; play_count: number }`; `sampleStats(range, limit?, granularity?)`.

- [ ] **Step 1: Generalize the trend query in queries.ts**

```ts
import trendWeeklySql from "@sql/trend_weekly.sql?raw";
import trendMonthlySql from "@sql/trend_monthly.sql?raw";

export type Granularity = "day" | "week" | "month";

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
```

Delete `dailyTrend()` and the `DailyTrend` interface; fix the imports in `api.ts` and `App.vue` (`DailyTrend` → `TrendPoint`).

- [ ] **Step 2: Granularity-aware sample bucketing in api.ts**

`sampleStats(range: Range, limit = 10, granularity: Granularity = "day")`; replace the `byDay` block's key computation:

```ts
function trendKey(d: Date, g: Granularity): string {
  if (g === "month")
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
  const day = new Date(d);
  if (g === "week") day.setDate(day.getDate() - ((day.getDay() + 6) % 7)); // back to Monday
  return `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, "0")}-${String(day.getDate()).padStart(2, "0")}`;
}
```

…and use `trendKey(new Date(r.played_at), granularity)` as the map key. Rename the local `dailyTrend` variable/field only if the compiler forces it — the `SampleData` field name stays `dailyTrend`.

- [ ] **Step 3: Toggles + trend-only refresh in App.vue**

```ts
const trendMetric = ref<"plays" | "mins">("mins");
const trendGranularity = ref<Granularity>("day");

async function refreshTrend() {
  const { current } = toRanges(range.value);
  daily.value = usingSample.value
    ? sampleStats(current, 20, trendGranularity.value).dailyTrend
    : await trend(current, trendGranularity.value);
}
watch(trendGranularity, refreshTrend);
```

In `loadFromDb`: `dailyTrend(current)` → `trend(current, trendGranularity.value)`.
In `loadFromSample`: `sampleStats(current, 20, trendGranularity.value)`.

```ts
const trendTraces = computed(() => [
  {
    type: "scatter" as const,
    mode: "lines" as const,
    x: daily.value.map((d) => d.bucket),
    y: daily.value.map((d) => (trendMetric.value === "plays" ? d.play_count : d.total_mins)),
    line: { color: seriesColor.value, width: 2 },
    hovertemplate:
      trendMetric.value === "plays" ? "%{y} plays<extra></extra>" : "%{y} min<extra></extra>",
  },
]);
```

Card template (replaces the three TODO comments):

```html
<div class="card-head">
  <h3>Listening Trend</h3>
  <div>
    <button class="range-btn" :class="{ current: trendMetric === 'plays' }" @click="trendMetric = 'plays'">Plays</button>
    <button class="range-btn" :class="{ current: trendMetric === 'mins' }" @click="trendMetric = 'mins'">Listening time</button>
    <button v-for="g in (['day', 'week', 'month'] as const)" :key="g" class="range-btn"
      :class="{ current: trendGranularity === g }" @click="trendGranularity = g">{{ g }}</button>
  </div>
</div>
```

- [ ] **Step 4: Typecheck**

Run: `cd apps/tauri && npx vue-tsc --noEmit`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add apps/tauri/src
git commit -m "feat(tauri): listening-trend metric toggle + day/week/month granularity"
```

---

### Task 5: Final verification

- [ ] **Step 1: Full checks**

Run: `uv run pytest` → green; `cd apps/tauri && npx vue-tsc --noEmit` → clean.

- [ ] **Step 2: Visual pass**

Run: `cd apps/tauri && npm run tauri dev`. Verify:
- Custom dates drive all cards + deltas; inputs reject dates before the earliest play / after today; presets clear the custom dates.
- Top tables scroll at 20 rows with sticky headers.
- Both charts toggle Plays / Listening time (hover text follows).
- Trend switches day/week/month without a full-dashboard reload.
- Browser `npm run dev` sample mode mirrors all of the above.

- [ ] **Step 3: Commit any fixes**

```bash
git add -A apps/tauri packages/core
git commit -m "fix(tauri): visual-pass fixes for dashboard TODO features"
```
