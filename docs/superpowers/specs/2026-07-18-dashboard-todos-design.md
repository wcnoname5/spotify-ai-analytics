# Dashboard TODOs — custom range, table scroll, chart toggles (2026-07-18)

Implements the four TODO clusters in `apps/tauri/src/App.vue`. Worker stays frozen; all
data changes are local `.sql` / TS. Files touched: `App.vue`, `lib/queries.ts`,
`lib/api.ts`, `styles.css`, and one shared SQL file
`packages/core/spotify_core/db/sql/plays_by_hour.sql`.

## 1. Custom date range picker

- Two native `<input type="date">` (from / to) in the `.filters` row, after the preset
  buttons. No picker library.
- Range state widens: `ref<RangeKey | "custom">`. Editing either date input switches to
  `"custom"`; clicking a preset clears both inputs and reselects the preset.
- `toRanges()` gains a custom branch:
  - `current.start` = from-date at **local** midnight → ISO; `current.end` = to-date at
    local 23:59:59.999 → ISO.
  - `previous` = the equal-length window immediately before `current.start` (deltas work
    exactly as with presets).
  - If only one input is filled, that side bounds the range and the other is open
    (`null`); `previous` is undefined for an open range, so deltas hide (same as All
    time).
- Input validation via native `min`/`max` attributes: `max` = today's local date on both
  inputs; `min` = the earliest `played_at` in the DB, fetched once on mount through a new
  `dataRange()` wrapper in `queries.ts` over the **already-existing** `data_range.sql`
  (no new SQL). Browser/sample build: `min` left unset. Beyond that, no validation UI;
  if from > to the queries return empty and the dashboard shows "No data in this
  period."

## 2. Top Artists / Top Tracks — scrollable, 20 rows

- Fetch limit 10 → 20 in `App.vue` (both `topArtists` and `topTracks` calls, and the
  `sampleStats` limit).
- Wrap each table in a scroll container with a CSS `max-height` + `overflow-y: auto`,
  same pattern as the existing `.recent-table-scroll`. Reuse or generalize that class in
  `styles.css` (e.g. rename to `.table-scroll` used by all three tables). Sticky
  `<thead>` if `.recent-table-scroll` already does it; otherwise plain scroll.
- No slider control, no JS.

## 3. Daily Activity Pattern — metric toggle

- Card header becomes a flex row: title left, a two-button toggle right — options
  **Plays** / **Listening time**. Buttons reuse the `.range-btn` style; state is a local
  `ref<"plays" | "mins">`. No new component.
- **SQL change (the only one):** `plays_by_hour.sql` adds
  `SUM(ms_played) / 60000 AS total_mins`. Param convention unchanged (`?1` start, `?2`
  end, `?3` tz). No Python caller exists (TS-only by design, per session notes), so no
  Python changes; run `uv run pytest` anyway.
- `queries.ts` `PlaysByHour` interface gains `total_mins: number`.
- `hourTraces` picks `play_count` or `total_mins` per the toggle; hovertemplate switches
  between "%{y} plays" and "%{y} min".
- `api.ts` `sampleStats` playsByHour aggregation also sums minutes per hour.

## 4. Listening Trend — metric toggle + granularity

- Same metric toggle (Plays / Listening time) as §3, independent state per card.
- A second toggle group: **Day / Week / Month**, state `ref<"day" | "week" | "month">`.
- `queries.ts`: replace `dailyTrend(range)` with `trend(range, granularity)` that
  selects among the already-existing `trend_daily.sql` / `trend_weekly.sql` /
  `trend_monthly.sql` imports (all return `bucket, total_mins, play_count`; weekly
  buckets are ISO-Monday dates, monthly are `YYYY-MM`). **Zero SQL changes.**
- Changing granularity re-runs only the trend query, not the whole `load()`.
- `trendTraces` picks the metric per the toggle; hovertemplate follows.
- `api.ts`: `sampleStats` trend bucketing gains the granularity (day key → week-Monday
  key / `YYYY-MM` key); browser build mirrors the real behavior.

## Out of scope

- Persisting toggle/range state across launches.
- Worker or D1 changes (frozen), report button, packaging items — tracked in the
  session-summary roadmap.
- Range-scoping Recently Played (known ride-list item, unchanged).

## Verification

- `cd worker && npm run typecheck` untouched; `apps/tauri` `npx vue-tsc --noEmit` (or
  the build) passes.
- `uv run pytest` green (SQL file shared with Python packaging).
- Visual check in `npm run tauri dev`: custom range drives all cards + deltas; tables
  scroll at 20 rows; both charts toggle metric; trend switches day/week/month.
