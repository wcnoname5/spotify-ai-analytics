# Shared SQL Module + Local-Cache Dashboard Design

**Date:** 2026-07-16
**Status:** Implemented (branch `frontend-tauri`, PR #14)
**Scope:** Extract analytics SQL into shared `.sql` files usable from both Python (MCP / AI report) and TypeScript (Tauri dashboard); add startup incremental sync to the Tauri app; switch the dashboard from frontend-JS aggregation over raw rows to local SQLite queries.

## Decisions (settled with user)

1. **One shared cache**: the Tauri app reads/writes the same `data/history.db` as MCP/report (path from `HISTORY_DB_PATH`, same default as Python's `paths.history_db()`).
2. **Timezone**: the dashboard uses the machine's timezone (`Date.getTimezoneOffset()`); the conn_country inference table stays Python-only (for historical export analysis in report/MCP).
3. **Full scope**: includes the dashboard switchover; the raw-rows-over-Vite-proxy path is deleted.
4. **Dev workflow**: `npm run tauri dev` is the daily driver; pure-browser `npm run dev` keeps only the sample-data UI preview.
5. **No new env vars**: TS reads the existing repo-root `.env` (`HISTORY_DB_PATH`, `WORKER_URL`, `WORKER_AUTH_TOKEN`) via `loadEnv(mode, <repo root>, '')` + `define` in `vite.config.ts` — one variable per fact, shared with Python, identical fallback defaults.
6. **Minimal testing**: no new test suites. Guards are the existing pytest suite, worker/app typecheck, and one up-front spike (see Risks).

## Architecture

```
Spotify API ──cron──▶ Worker ──▶ D1 (source of truth)
                        │
              GET /api/tracks?since=      (Worker stays frozen at its current endpoints)
                        ▼
              data/history.db (single shared pull-only cache)
               ▲            ▲             ▲
        local_sync.py    MCP / report   Tauri dashboard
        (CLI trigger)    (Python)       (TS, syncs on app startup)
```

- Sync is **not** Tauri-exclusive. Each consumer triggers the same tiny idempotent logic: `MAX(played_at)` as cursor → `GET /api/tracks?since=` → `INSERT OR IGNORE`. Python already has it (`spotify_core/db/local_sync.py`); TS gets its own ~40-line `syncOnStartup()`.
- Local cache is pull-only; nothing local ever writes to D1. Concurrent syncs are safe (idempotent inserts; SQLite in WAL mode).
- No Worker aggregation endpoints, ever: all analytics queries run locally, so new filters/date ranges are pure SQL changes with no Worker deploy.

## Component 1 — shared SQL module: `packages/core/spotify_core/db/sql/`

One statement per file, loaded as text by both languages:

| File | Replaces |
|---|---|
| `schema.sql` | DDL moved out of `schema.py` (which now reads this file — still no second schema) |
| `top_artists.sql`, `top_tracks.sql` | `get_top_artists` / `get_top_tracks` |
| `listening_summary.sql` | `get_listening_summary` |
| `recent_plays.sql` | `get_recent_plays` |
| `trend_daily.sql`, `trend_weekly.sql`, `trend_monthly.sql` | `_grouped_trend` variants |
| `activity_pattern.sql` | `get_daily_activity_pattern` |
| `data_range.sql`, `max_played_at.sql` | `get_data_range` / sync cursor |
| `insert_track.sql` | insert in `local_sync.py` and TS sync |

`get_listening_patterns` (peak hour / peak day / most active date) decomposes into a few small `.sql` files as well; its Python function keeps composing them.

**Conventions (what makes one file work in both `sqlite3` and tauri-plugin-sql/sqlx):**

1. SQLite-native indexed params `?1`, `?2` (repeatable within a statement).
2. Optional filters as NULL-guards baked into the SQL: `(?1 IS NULL OR played_at >= ?1)` — no programmatic WHERE assembly anywhere.
3. Timezone modifier is a bound param: `datetime(played_at, ?3)` with a string like `'+8 hours'`. Each language decides the value (Python: conn_country inference; TS: machine timezone).
4. `track_id` is always selected; the `show_track_id` flag is deleted (callers drop the column if unwanted).

**Division of labor:** `.sql` files are the single source of truth for query logic (skip threshold, week start, segment boundaries). Shaping — dict/object assembly, weekday names, sort order — stays per-language and thin.

## Component 2 — Python refactor (`queries.py`, `local_sync.py`, `schema.py`)

- `queries.py` public signatures unchanged (minus `show_track_id`) so MCP tools, report, and existing tests need no changes; bodies become: load `.sql` via `importlib.resources` → execute → shape.
- `_detect_tz_offset` + country table stay in Python, now feeding the tz bound param.
- `local_sync.py` switches its inline SQL to `insert_track.sql` / `max_played_at.sql`.
- `schema.py` reads `schema.sql` instead of embedding the DDL string.
- Acceptance: `uv run pytest` green.

## Component 3 — TS data layer (`apps/tauri/src/lib/`)

- `db.ts`: opens the shared db via tauri-plugin-sql (sqlite), absolute path injected from `HISTORY_DB_PATH` (fallback: resolved `<repo>/data/history.db`), enables WAL. If the db file/table is missing, runs `schema.sql` first.
- SQL loading: Vite alias `@sql` → `packages/core/spotify_core/db/sql`, imported with `?raw` (embedded at build time; needs `server.fs.allow` for the path outside the app root).
- `queries.ts`: one thin wrapper per `.sql` file mirroring the Python names; tz param computed from `Date.getTimezoneOffset()`.
- `sync.ts`: `syncOnStartup()` — cursor from `max_played_at.sql` → `fetch(GET /api/tracks?since=)` with Bearer from injected `WORKER_AUTH_TOKEN` → sequential `insert_track.sql` (no wrapping transaction: sqlx pooling routes COMMIT unreliably; inserts are idempotent).

## Component 4 — dashboard switchover and deletions

- Components call `queries.ts`; the JS aggregation in `stats.ts` and the Vite-proxy raw-rows fetch path are deleted.
- Sample-data fallback remains solely for pure-browser UI preview (`npm run dev`).

## Error handling

- Sync failure (offline / Worker down): render from the existing cache; show a non-blocking "data not refreshed" notice.
- Missing db **and** offline: sample-data fallback.
- Empty result sets: queries return empty arrays; existing empty states cover the UI.
- Idempotent `INSERT OR IGNORE` makes a crashed/partial sync harmless — next startup re-pulls from the same cursor.

## Explicitly deferred

- Token storage in OS keychain (Rust-side Worker calls).
- Packaged-app db path strategy (appDataDir vs configured path).
- Worker CORS headers (only needed for a pure-browser deployment that may never happen).
- Materialized/pre-aggregated tables — 74k rows with the existing `idx_listening_history_played_at` index is milliseconds; revisit only if measurably slow.
- Token storage: `loadEnv`/`define` puts `WORKER_AUTH_TOKEN` into the dev bundle — acceptable for local dev; must move to Rust-side keychain before any packaged distribution.
