# Local DB-backed Dashboard — Design

**Date:** 2026-05-21
**Status:** Approved design. Ready for implementation planning.
**Owner:** wcnoname5
**Relates to:** `2026-05-15-chatbot-platform-roadmap.md` (this work pulls the dashboard
sub-project forward and rebuilds it; see §8).

---

## 1. Goal

Re-scope `apps/web` into a **DB-backed, dashboard-first** local Streamlit app. The
dashboard reads exclusively from `history.db` via SQL queries and matches the
hand-drawn layout (period filter + sync button, top-stats, two plots, recent-50
table). The chat page becomes a placeholder shell pending the Chainlit migration.

First-time setup (Spotify OAuth + bulk JSON import) stays with the existing MCP
wizard / CLI — a one-time terminal step, out of scope here. Day-to-day use is a
double-click `.bat` launcher with no typed commands.

### Non-goals

- No new chat functionality. `chatbot_page.py` becomes a placeholder.
- No schema migration. `track_id` already stores the full Spotify URI.
- No change to `packages/core/spotify_core/agent/` — the agent code stays for the
  later Chainlit app.
- No initial-import UI inside the dashboard — that remains the wizard's job.

---

## 2. Key decisions (resolved during brainstorming)

| Decision | Choice |
|---|---|
| App structure | Rewrite the existing `apps/web` app (not a separate app) |
| Schema | **No change.** `listening_history.track_id` already holds `spotify:track:...` URIs |
| Plot 2 granularity | Three-tier auto-switch by period length |
| Launcher | `.bat` file at repo root |

**Schema rationale:** Verified against the real `data/history.db` (65,194 rows):
the `track_id` column contains values like `spotify:track:0VPNZYwb5PFmHmMXsul9IK`.
The JSON dataloader maps `spotify_track_uri` → `track_uri`, and the pipeline writes
that into the `track_id` DB column. The column is named misleadingly but the URI is
already present. Adding a `spotify_track_uri` column would be a cosmetic migration
touching the pipeline, every query, and the MCP adapter — rejected.

---

## 3. Data layer — new SQL queries

Four new functions are added to
[`packages/core/spotify_core/db/queries.py`](../../../packages/core/spotify_core/db/queries.py).
They reuse the existing private helpers (`_ensure_history_db`,
`_validate_date_range`, `_detect_tz_offset`, `_DOW_MAP`) and group on **local time**
(UTC offset inferred from `conn_country`), consistent with `get_listening_patterns`.

Date-range filtering keeps the existing pattern: `WHERE played_at >= start_date AND
played_at <= end_date + "T23:59:59Z"` on the raw UTC `played_at`. Local-time
conversion applies only to the grouping expressions.

### Targeted refactor

The date-window WHERE-clause builder is currently duplicated in every query.
Extract it into a small private helper (`_date_window(start, end) -> (sql, params)`)
in `queries.py` so the four new queries and the existing ones share one
implementation. This is the only refactor in scope — no unrelated cleanup.

### 3.1 `get_daily_activity_pattern(db_path, start_date=None, end_date=None) -> list[dict]`

Per-weekday, per-time-segment listening volume for the **Plot 1** stacked bar.

- Time segments (local hour-of-day), per the sketch: `0–6`, `7–12`, `13–18`, `19–23`.
- Returns one row per (weekday, segment) combination present in the data:
  `{"weekday": str, "weekday_idx": int, "segment": str, "total_ms": int}`.
  - `weekday`: `"Mon".."Sun"`; `weekday_idx`: `0` (Mon) .. `6` (Sun) for ordering.
  - `segment`: stable label, one of `"0-6"`, `"7-12"`, `"13-18"`, `"19-23"`.
- SQL: local timestamp via `datetime(played_at, '<±N> hours')`, then
  `strftime('%w', local_ts)` for day-of-week and a `CASE` over
  `CAST(strftime('%H', local_ts) AS INTEGER)` for the segment; `GROUP BY weekday, segment`, `SUM(ms_played) AS total_ms`.

### 3.2 `get_daily_trend(db_path, start_date=None, end_date=None) -> list[dict]`

Per-calendar-day totals for the **Plot 2** short-period tier.
Returns `[{"date": "YYYY-MM-DD", "total_ms": int, "play_count": int}]`, ordered by
date ascending. Day is the local calendar date.

### 3.3 `get_weekly_trend(db_path, start_date=None, end_date=None) -> list[dict]`

Per-ISO-week totals for the **Plot 2** mid-period tier.
Returns `[{"week_label": str, "total_ms": int, "play_count": int}]`, ordered
ascending. `week_label` is `strftime('%Y-W%W', local_ts)` (Monday-based week).

### 3.4 `get_monthly_trend(db_path, start_date=None, end_date=None) -> list[dict]`

Per-month totals for the **Plot 2** long-period tier.
Returns `[{"month_label": "YYYY-MM", "total_ms": int, "play_count": int}]`, ordered
ascending.

### Reused as-is

`get_top_artists`, `get_top_tracks(show_track_id=True)`,
`get_recent_plays(show_track_id=True)`, `get_listening_summary`, `is_history_empty`,
`get_data_range`.

---

## 4. UI layer — `apps/web` restructure

| File | Action |
|---|---|
| `ui/main_page.py` | Slim down: drop AI-model/API-key UI and JSON-upload; keep Dashboard/Chat nav + a data-status caption |
| `ui/dashboard.py` | Rewrite as DB-backed (orchestration only) |
| `ui/dashboard_charts.py` | **New.** Pure `data → plotly.graph_objects.Figure` builders (unit-testable) |
| `ui/chatbot_page.py` | Replace body with a placeholder shell + `# TODO` |
| `ui/time_analysis.py` | **Delete** (Polars-based, superseded) |
| `ui/track_analysis.py` | **Delete** (Polars-based, superseded) |
| `spotify_web/session.py` | Trim to what the DB dashboard needs; **delete if nothing remains** (all current contents are agent/loader plumbing) |
| `spotify_web/config.py` | **New.** Resolves sync credentials (see §6) |

`packages/core/spotify_core/agent/` is untouched.

---

## 5. Dashboard layout

Rendered by `render_dashboard()` in `ui/dashboard.py`, matching the sketch:

1. **Header row** — period filter (`本周` / `本月` / `自訂時間`) on the left, `Sync`
   button on the right.
   - `本周`: Monday of the current week → today.
   - `本月`: 1st of the current month → today.
   - `自訂時間`: two `st.date_input` widgets (start / end).
   - Produces `(start_date, end_date)` as ISO `YYYY-MM-DD` strings for all queries.
2. **Summary metrics** — `st.metric` row from `get_listening_summary`: total plays,
   listening minutes, unique artists, unique tracks for the selected range.
3. **Stats** — two columns:
   - Left: **Top 5 artists** from `get_top_artists(limit=5)`, showing listening time
     (ms formatted to hours/minutes).
   - Right: **Top 5 tracks** from `get_top_tracks(limit=5, show_track_id=True)`,
     showing play count and a Spotify link. Rendered with `st.dataframe` +
     `st.column_config.LinkColumn`; the URI `spotify:track:<id>` is converted to
     `https://open.spotify.com/track/<id>`.
4. **Plot 1 — daily activity pattern** — `dashboard_charts.daily_activity_figure()`:
   stacked bar, x = Mon–Sun, y = minutes, stacked by the four time segments. Reuses
   the daytime color scheme from the old `time_analysis.py`.
5. **Plot 2 — trend (three-tier auto-switch)** by period span
   `days = (end - start).days + 1`:
   - `days <= 14` → `get_daily_trend` (daily bar).
   - `15 <= days <= 92` → `get_weekly_trend` (weekly bar).
   - `days > 92` → `get_monthly_trend` (monthly bar).
6. **Recent 50** — `get_recent_plays(limit=50, show_track_id=True)`, the DB's most
   recent 50 plays (not period-filtered), as an `st.dataframe` with track / artist /
   album / played_at columns plus a Spotify `LinkColumn`.

### Spotify URI → URL

Helper: split `spotify:track:<id>` on `:` → `https://open.spotify.com/track/<id>`.
If the value is not a `spotify:track:` URI (e.g. a podcast episode), render no link.

### Caching

Each query call is wrapped in `@st.cache_data` keyed by `(db_path: str,
start_date: str, end_date: str)` — all hashable, and the queries return plain
lists/dicts. A short `ttl` matches the existing dashboard convention. After a
successful sync, `st.cache_data.clear()` is called explicitly so stale results are
dropped (cache keys cannot detect DB content changes).

---

## 6. Sync button

Calls `sync_api_to_db(db_path, tokens_db_path, user_id, client_id, fernet_key)` from
`packages/core/spotify_core/db/pipeline.py`.

Credentials are resolved by the new `apps/web/spotify_web/config.py`, mirroring
`apps/mcp/spotify_mcp/config.py`:

- `db_path`, `tokens_db_path`, `user_id` — from `spotify_core.config.settings`.
- `client_id` — `SPOTIFY_CLIENT_ID` from env, after `load_dotenv(paths.env_file())`.
- `fernet_key` — `TOKEN_ENCRYPT_KEY` from env, `.encode()`.

Behavior:

- On success: `st.toast` with the inserted count → `st.cache_data.clear()` →
  `st.rerun()`.
- No OAuth tokens (`sync_api_to_db` raises `RuntimeError`): catch it and show a
  friendly `st.error` telling the user to run the setup wizard first.
- Other exceptions: caught, logged, shown via `st.error` — the page stays usable.

---

## 7. Launcher — `run_dashboard.bat`

At the repo root. It gates startup on a readiness check (`spotify-mcp doctor`,
which exits non-zero when setup is incomplete) and, if needed, runs the existing
interactive setup wizard (`spotify-mcp setup`) before launching the dashboard:

```bat
@echo off
cd /d "%~dp0"
set SPOTIFY_MCP_DATA_DIR=%~dp0data
uv run spotify-mcp doctor
if errorlevel 1 (
    echo Setup incomplete - launching setup wizard...
    uv run spotify-mcp setup
)
uv run streamlit run apps/web/ui/main_page.py
```

- `SPOTIFY_MCP_DATA_DIR` points `paths.history_db()` at the repo's `data/history.db`.
- **First run** — `doctor` fails → the wizard walks the user through OAuth and
  history import; then the dashboard opens.
- **Subsequent runs** — `doctor` passes → straight to the dashboard.
- If the user cancels or leaves the wizard incomplete, the dashboard still opens and
  falls back to the in-app empty-state guidance (§9) — the `.bat` does not loop.
- Double-click opens the browser; a background terminal window shows logs but needs
  no typed input. Requires `uv` installed and on PATH; the `spotify-mcp` CLI is
  provided by the `apps/mcp` package in the uv workspace.

---

## 8. Chat placeholder

`ui/chatbot_page.py` is replaced with a minimal page: a heading and a message —
"💬 Chat is under construction" A `# TODO` comment in the code marks the migration point. 
The `Chat` nav entry remains.

---

## 9. Error / empty-state handling

- **Missing or empty DB** — `is_history_empty(db_path)` is checked at the top of
  `render_dashboard()`. If true: show a guidance message (import history via the
  wizard, or use the `Sync` button to pull the recent 50). The `Sync` button is
  still rendered; charts and stats are skipped.
- **Query exceptions** — caught per-section, shown via `st.error`; one failing
  section does not blank the whole page.
- **No data in the selected range** — each section shows an `st.info` "no data"
  notice instead of an empty chart.

---

## 10. Testing (TDD)

Tests are written before the implementation.

- **New queries** — `tests/core/` test file against a temporary SQLite DB seeded
  with fixture rows: time-segment bucketing, weekday grouping, weekly/monthly
  grouping, date-range filtering, and empty-DB behavior for each of the four new
  queries.
- **Chart builders** — `tests/web/` test file: `dashboard_charts.py` functions are
  pure (`data → Figure`), so assert each produces a `Figure` with the expected
  number of traces / data for representative inputs and for empty input.
- **Streamlit render** — not unit-tested; verified manually via the `.bat`
  launcher.

---

## 11. Roadmap update

[`2026-05-15-chatbot-platform-roadmap.md`](2026-05-15-chatbot-platform-roadmap.md)
has been updated (done 2026-05-21):

- §2.2 — the dashboard is now described as **rebuilt as a DB-backed app**, pulled
  forward ahead of the chatbot sub-projects.
- §3 — row **H** is redefined as this dashboard rebuild (dependency `—`, pulled
  forward); the experiment-results page formerly bundled into H is split out as a
  new row **I**; the execution order becomes `H → A → B → C → (D ∥ E ∥ F) → G`.
