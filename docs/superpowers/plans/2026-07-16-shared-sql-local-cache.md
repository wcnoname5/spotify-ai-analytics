# Shared SQL Module + Local-Cache Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One set of `.sql` files drives analytics in both Python (MCP/report) and TypeScript (Tauri dashboard); the dashboard reads the shared `data/history.db` cache and syncs it incrementally on startup.

**Architecture:** Per spec `docs/superpowers/specs/2026-07-16-shared-sql-local-cache-design.md`. SQL files in `packages/core/spotify_core/db/sql/` are the single source of truth for query logic; each language keeps a thin wrapper + shaping. Tauri uses tauri-plugin-sql against the same db file Python uses; Worker stays frozen.

**Tech Stack:** Python 3.12/uv/sqlite3, Tauri 2 + @tauri-apps/plugin-sql, Vite 6, Vue 3.

## Global Constraints

- `uv` for all Python deps; `uv run pytest` must be green before a task is done
- Never commit `data/*.db` or `.env`
- D1 access only via Worker; local SQLite is a pull-only cache
- No second schema: DDL lives in `sql/schema.sql`, everything reads it
- **No new tests** (user decision) — guards are existing pytest, `vue-tsc`, and the Task 1 spike
- **No new env vars** — TS reads root `.env`'s existing `HISTORY_DB_PATH`, `WORKER_URL`, `WORKER_AUTH_TOKEN`
- SQL param conventions: indexed `?1..?N`; optional filters as `(?1 IS NULL OR ...)`; tz modifier bound as param

---

### Task 1: Spike — one shared query in both runtimes

**Files:**
- Create: `packages/core/spotify_core/db/sql/top_artists.sql`
- Modify: `apps/tauri/package.json`, `apps/tauri/src-tauri/Cargo.toml`, `apps/tauri/src-tauri/src/lib.rs`, `apps/tauri/src-tauri/capabilities/default.json`

**Produces:** proof that `?1` indexed params + NULL-guards work identically in `sqlite3` and tauri-plugin-sql (sqlx). If sqlx rejects `?N`, switch convention to plain `?` with documented param order and update the spec note.

- [ ] Write `top_artists.sql`:

```sql
SELECT artist_name,
       SUM(ms_played) / 60000 AS total_mins,
       COUNT(*) AS play_count
FROM listening_history
WHERE artist_name IS NOT NULL
  AND (?1 IS NULL OR played_at >= ?1)
  AND (?2 IS NULL OR played_at <= ?2)
GROUP BY artist_name
ORDER BY total_mins DESC
LIMIT ?3
```

(top_artists has no `track_id` — its grain is the artist. Track-grain files always include `track_id`.)

- [ ] Python check (throwaway, don't commit): `uv run python -c "..."` executing the file against `data/history.db` with `(None, None, 5)` and `('2026-06-01', '2026-07-16T23:59:59Z', 5)` — both return rows.
- [ ] Install plugin: in `apps/tauri` run `npm run tauri add sql` (adds npm pkg, Cargo dep `tauri-plugin-sql` with `sqlite` feature, registers plugin in `lib.rs`); add `"sql:default"` (or `sql:allow-load`/`allow-select`/`allow-execute`) to `capabilities/default.json`. Enable sqlx sqlite feature: `tauri-plugin-sql = { features = ["sqlite"] }`.
- [ ] Tauri check (throwaway code in `App.vue` mounted hook): `Database.load('sqlite:<abs path>')` then `db.select(topArtistsSql, [null, null, 5])` — logs rows. Run `npm run tauri dev`.
- [ ] Commit plugin wiring + the `.sql` file: `git commit -m "feat: tauri-plugin-sql wiring + first shared .sql (spike verified)"`

### Task 2: Extract all SQL files

**Files:**
- Create in `packages/core/spotify_core/db/sql/`: `schema.sql`, `top_tracks.sql`, `listening_summary.sql`, `recent_plays.sql`, `trend_daily.sql`, `trend_weekly.sql`, `trend_monthly.sql`, `activity_pattern.sql`, `plays_by_hour.sql`, `data_range.sql`, `max_played_at.sql`, `insert_track.sql`, `patterns_peak_hour.sql`, `patterns_peak_dow.sql`, `patterns_top_date.sql`, `patterns_date_detail.sql`, `patterns_avg_per_day.sql`

**Interfaces (param order, uniform):** `?1`=start (ISO or NULL), `?2`=end (ISO, already end-of-day-widened by caller, or NULL), `?3`=tz modifier string (e.g. `'+8 hours'`) where the query groups by local time, trailing params for LIMIT where applicable. `insert_track.sql` takes the 14 columns in `local_sync._COLUMNS` order. `max_played_at.sql`: `SELECT MAX(played_at) AS c FROM listening_history`.

- [ ] Port each query from `queries.py` (and `local_sync.py`'s INSERT) applying the conventions; every row-returning file SELECTs `track_id` where the grain has one. Example pattern for tz-grouped files (`trend_daily.sql`):

```sql
SELECT date(datetime(played_at, ?3)) AS bucket,
       SUM(ms_played) / 60000 AS total_mins,
       COUNT(*) AS play_count
FROM listening_history
WHERE (?1 IS NULL OR played_at >= ?1)
  AND (?2 IS NULL OR played_at <= ?2)
GROUP BY bucket
ORDER BY bucket
```

- [ ] `schema.sql` = full-column `listening_history` DDL (base columns + the 6 export columns from `migrations._HISTORY_COLUMNS`) + `sync_state` + the `played_at` index, statements separated by `;`.
- [ ] `plays_by_hour.sql` (new, for the dashboard's hourly bar): `SELECT CAST(strftime('%H', datetime(played_at, ?3)) AS INTEGER) AS hour, COUNT(*) AS play_count ... GROUP BY hour ORDER BY hour` with the same NULL-guards.
- [ ] Commit: `git commit -m "feat: extract analytics SQL into shared sql/ module"`

### Task 3: Python refactor to load the shared SQL

**Files:**
- Modify: `packages/core/spotify_core/db/queries.py`, `schema.py`, `local_sync.py`
- Possibly modify: `pyproject.toml`/package data config so `sql/*.sql` ships with the package

**Interfaces:** all public function signatures in `queries.py` unchanged, except `show_track_id` params deleted (results now always include `track_id`). Update the two MCP/report call sites that pass `show_track_id`.

- [ ] Add loader in `queries.py`:

```python
from importlib.resources import files

def _sql(name: str) -> str:
    return files("spotify_core.db.sql").joinpath(f"{name}.sql").read_text()
```

(plus `sql/__init__.py` empty file so `importlib.resources` resolves the package)

- [ ] Rewrite each query function: keep `_validate_date_range`/`_ensure_history_db`/shaping; replace dynamic SQL with `conn.execute(_sql("top_artists"), (start, end_widened, limit))`. End-of-day widening moves from `_date_window` into a small `_widen_end(end_date)` helper; `_date_window` is deleted. tz functions bind `tz_mod` as `?3`.
- [ ] `schema.py`: read `schema.sql`, split on `;`, expose the same `HISTORY_DDL`/`ALL_DDL` lists (tokens DDL stays inline — Python-only).
- [ ] `local_sync.py`: use `_sql("insert_track")` and `_sql("max_played_at")`.
- [ ] Run: `uv run pytest` → green (fix fallout from `show_track_id` removal). Grep for stale callers: `rg show_track_id`.
- [ ] Commit: `git commit -m "refactor: queries.py/schema.py/local_sync.py load shared .sql files"`

### Task 4: TS data layer + startup sync

**Files:**
- Modify: `apps/tauri/vite.config.ts`
- Create: `apps/tauri/src/lib/db.ts`, `apps/tauri/src/lib/queries.ts`, `apps/tauri/src/lib/sync.ts`
- Modify: `apps/tauri/src/vite-env.d.ts` (declare `*.sql?raw` module + injected consts)

**Interfaces produced (consumed by Task 5):**
- `queries.ts`: `listeningSummary(range)`, `topArtists(range, limit)`, `topTracks(range, limit)`, `recentPlays(limit)`, `dailyTrend(range)`, `playsByHour(range)` — `range = { start: string | null; end: string | null }`, return shapes mirror the SQL column names (`total_mins`, `play_count`, …)
- `sync.ts`: `syncOnStartup(): Promise<{ inserted: number } | { offline: true }>`

- [ ] `vite.config.ts`: replace the hand-rolled `repoEnv()` + `/api` proxy with `loadEnv(mode, resolve(__dirname, "../.."), "")`; add:

```ts
resolve: { alias: { "@sql": resolve(__dirname, "../../packages/core/spotify_core/db/sql") } },
server: { fs: { allow: [resolve(__dirname, "../..")] }, ... },
define: {
  __HISTORY_DB_PATH__: JSON.stringify(env.HISTORY_DB_PATH || resolve(__dirname, "../../data/history.db")),
  __WORKER_URL__: JSON.stringify(env.WORKER_URL ?? ""),
  __WORKER_AUTH_TOKEN__: JSON.stringify(env.WORKER_AUTH_TOKEN ?? ""), // dev-only; keychain before packaging
},
```

- [ ] `db.ts`: `Database.load("sqlite:" + __HISTORY_DB_PATH__)` (memoized); on first load run `schema.sql` split on `;` (idempotent `IF NOT EXISTS`), `PRAGMA journal_mode=WAL`. Export `isTauri = "__TAURI_INTERNALS__" in window`.
- [ ] `queries.ts`: import each `.sql?raw` via `@sql/...`; tz modifier helper:

```ts
const off = -new Date().getTimezoneOffset() / 60;
const tzMod = `${off >= 0 ? "+" : ""}${off} hours`;
```

one thin async wrapper per query binding `[start, end, tzMod, ...]` per the Task 2 param order (end already widened by caller in App.vue's range computation — ranges there are full ISO timestamps, so no widening needed on the TS side).
- [ ] `sync.ts`: cursor from `max_played_at.sql` (fallback `1970-01-01T00:00:00Z`) → `fetch(`${__WORKER_URL__}/api/tracks?since=${cursor}`, { headers: { Authorization: `Bearer ${__WORKER_AUTH_TOKEN__}` } })` → inside one transaction, `insert_track.sql` per row. Network/HTTP failure returns `{ offline: true }` — never throws.
- [ ] Run: `npm run build` (vue-tsc) → green. Commit: `git commit -m "feat: TS data layer over shared sql/ + startup incremental sync"`

### Task 5: Dashboard switchover + delete old paths

**Files:**
- Modify: `apps/tauri/src/App.vue`, `apps/tauri/src/lib/api.ts` (→ sample data only), `apps/tauri/src/lib/stats.ts` (gut aggregations)
- Delete: `/api` proxy remnants (done in Task 4), `fetchTracks`

**Consumes:** `queries.ts` + `sync.ts` from Task 4.

- [ ] `App.vue`: on mount, if `isTauri` → `await syncOnStartup()` (show a non-blocking "資料未更新" notice on `{offline: true}`) then load all sections via `queries.ts`; metric deltas = two `listeningSummary` calls (current + previous window). If not Tauri → sample mode.
- [ ] Sample fallback: keep `sampleTracks()`; keep only the minimal aggregation needed to feed the same shapes `queries.ts` returns (move/trim from `stats.ts` into `api.ts` as `sampleStats(range)`); delete `fetchTracks` and everything else in `stats.ts` except `formatMinutes`, `delta`, `spotifyUrl` (pure formatters — relocate into App.vue or a `format.ts` if imports get circular).
- [ ] Remove spike leftovers from Task 1's `App.vue` mounted hook.
- [ ] Verify: `npm run tauri dev` — real data renders, startup sync inserts new rows (check console count), charts match previous behavior; `npm run dev` (browser) still renders sample UI.
- [ ] Run: `npm run build` and `uv run pytest` → both green.
- [ ] Commit: `git commit -m "feat: dashboard reads local history.db via shared SQL; drop raw-rows proxy path"`
