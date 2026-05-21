# Local DB-backed Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild `apps/web` as a DB-backed, dashboard-first local Streamlit app — period filter, sync button, top-stats, two plots, recent-50 table — with a `.bat` launcher and a chat placeholder.

**Architecture:** Four new SQL chart queries are added to `spotify_core.db.queries` (reading `history.db` directly). Pure, unit-testable logic for the web app (sync-credential resolution, formatting helpers, Plotly figure builders) lives in the installed `spotify_web` package. The Streamlit page files in `apps/web/ui/` are thin orchestration layers that call into those modules. A `run_dashboard.bat` gates startup on `spotify-mcp doctor` and runs `spotify-mcp setup` when setup is incomplete.

**Tech Stack:** Python 3.12+, SQLite (`sqlite3`), Streamlit ≥1.52, Plotly, pytest, `uv` workspace.

**Spec:** `docs/superpowers/specs/2026-05-21-local-dashboard-design.md`

---

## File Structure

| File | Responsibility |
|---|---|
| `packages/core/spotify_core/db/queries.py` | **Modify** — add `_date_window` helper, refactor existing queries to use it, add 4 chart queries |
| `tests/core/test_chart_queries.py` | **Create** — tests for the 4 new queries |
| `apps/web/spotify_web/formatting.py` | **Create** — pure helpers: Spotify URI→URL, duration formatting |
| `apps/web/spotify_web/config.py` | **Create** — resolve sync-button credentials |
| `apps/web/spotify_web/charts.py` | **Create** — pure Plotly figure builders |
| `apps/web/spotify_web/session.py` | **Delete** — agent/loader plumbing, now unused |
| `tests/web/__init__.py` | **Create** — package marker |
| `tests/web/test_formatting.py` | **Create** |
| `tests/web/test_web_config.py` | **Create** |
| `tests/web/test_charts.py` | **Create** |
| `apps/web/ui/dashboard.py` | **Rewrite** — DB-backed dashboard page |
| `apps/web/ui/chatbot_page.py` | **Rewrite** — placeholder shell |
| `apps/web/ui/main_page.py` | **Rewrite** — slim sidebar + nav |
| `apps/web/ui/time_analysis.py` | **Delete** — Polars-based, superseded |
| `apps/web/ui/track_analysis.py` | **Delete** — Polars-based, superseded |
| `run_dashboard.bat` | **Create** — repo-root launcher |

> **Note (refinement of spec §4):** the spec named the chart module `ui/dashboard_charts.py`. It is placed in the installed `spotify_web` package instead (`spotify_web/charts.py`) so pytest can import it — the `ui/` directory is not an installed package. Same reasoning for `formatting.py`. The `ui/` files import from `spotify_web.*`.

All test commands use `uv run` per the project convention (CLAUDE.md). Commits use conventional-commit prefixes (`feat:`, `refactor:`, `test:`, `chore:`).

---

## Task 1: Extract `_date_window` helper and refactor existing queries

Adds a shared date-range WHERE-clause builder and routes the four existing
date-filtered queries through it. The existing `tests/core/test_queries.py` suite
is the regression guard — this is a pure refactor with no behavior change.

**Files:**
- Modify: `packages/core/spotify_core/db/queries.py`
- Test (regression only): `tests/core/test_queries.py`

- [ ] **Step 1: Add the `_date_window` helper**

In `packages/core/spotify_core/db/queries.py`, add this function immediately after
`_validate_date_range` (before `get_top_artists`):

```python
def _date_window(
    start_date: Optional[str], end_date: Optional[str]
) -> tuple[list[str], list]:
    """Return (where_clauses, params) for an inclusive played_at date range.

    end_date is widened to end-of-day so the boundary day is fully included.
    Either bound may be None; the matching clause is then omitted.
    """
    clauses: list[str] = []
    params: list = []
    if start_date:
        clauses.append("played_at >= ?")
        params.append(start_date)
    if end_date:
        clauses.append("played_at <= ?")
        params.append(end_date + "T23:59:59Z")
    return clauses, params
```

- [ ] **Step 2: Refactor `get_top_artists`**

In `get_top_artists`, replace this block:

```python
    where_clauses = ["artist_name IS NOT NULL"]
    params: list = []
    if start_date:
        where_clauses.append("played_at >= ?")
        params.append(start_date)
    if end_date:
        where_clauses.append("played_at <= ?")
        params.append(end_date + "T23:59:59Z")
```

with:

```python
    where_clauses = ["artist_name IS NOT NULL"]
    date_clauses, params = _date_window(start_date, end_date)
    where_clauses += date_clauses
```

- [ ] **Step 3: Refactor `get_top_tracks`**

In `get_top_tracks`, replace this block:

```python
    where_clauses = ["track_name IS NOT NULL"]
    params: list = []
    if start_date:
        where_clauses.append("played_at >= ?")
        params.append(start_date)
    if end_date:
        where_clauses.append("played_at <= ?")
        params.append(end_date + "T23:59:59Z")
```

with:

```python
    where_clauses = ["track_name IS NOT NULL"]
    date_clauses, params = _date_window(start_date, end_date)
    where_clauses += date_clauses
```

- [ ] **Step 4: Refactor `get_listening_summary`**

In `get_listening_summary`, replace this block:

```python
    where_clauses = []
    params: list = [_SKIP_THRESHOLD_MS]
    if start_date:
        where_clauses.append("played_at >= ?")
        params.append(start_date)
    if end_date:
        where_clauses.append("played_at <= ?")
        params.append(end_date + "T23:59:59Z")
```

with:

```python
    where_clauses, date_params = _date_window(start_date, end_date)
    params: list = [_SKIP_THRESHOLD_MS] + date_params
```

- [ ] **Step 5: Refactor `get_listening_patterns`**

In `get_listening_patterns`, replace this block:

```python
    where_clauses = []
    params: list = []
    if start_date:
        where_clauses.append("played_at >= ?")
        params.append(start_date)
    if end_date:
        where_clauses.append("played_at <= ?")
        params.append(end_date + "T23:59:59Z")
```

with:

```python
    where_clauses, params = _date_window(start_date, end_date)
```

- [ ] **Step 6: Run the regression suite**

Run: `uv run pytest tests/core/test_queries.py -v`
Expected: PASS — all existing tests still green (no behavior change).

- [ ] **Step 7: Commit**

```bash
git add packages/core/spotify_core/db/queries.py
git commit -m "refactor: extract _date_window helper in db/queries"
```

---

## Task 2: `get_daily_activity_pattern` query

Per-weekday × per-time-segment listening volume for the Plot 1 stacked bar.

**Files:**
- Modify: `packages/core/spotify_core/db/queries.py`
- Test: `tests/core/test_chart_queries.py`

- [ ] **Step 1: Write the failing test**

Create `tests/core/test_chart_queries.py`:

```python
"""Tests for the dashboard chart queries in db/queries.py."""
from spotify_core.db.migrations import init_history_db, get_connection
from spotify_core.db.queries import (
    get_daily_activity_pattern,
    get_daily_trend,
    get_weekly_trend,
    get_monthly_trend,
)


def _seed(db_path: str, rows: list[dict]) -> None:
    """Insert minimal listening_history rows for chart-query tests."""
    conn = get_connection(db_path)
    with conn:
        for r in rows:
            conn.execute(
                "INSERT OR IGNORE INTO listening_history "
                "(id, track_id, track_name, artist_name, played_at, ms_played, source) "
                "VALUES (?, ?, ?, ?, ?, ?, 'json_import')",
                (
                    r["id"], r.get("track_id", r["id"]),
                    r.get("track_name", "T"), r.get("artist_name", "A"),
                    r["played_at"], r["ms_played"],
                ),
            )
    conn.close()


def test_daily_activity_pattern_buckets(tmp_path):
    db = str(tmp_path / "history.db")
    init_history_db(db)
    _seed(db, [
        {"id": "1", "played_at": "2024-01-08T03:00:00Z", "ms_played": 60_000},   # Mon, 0-6
        {"id": "2", "played_at": "2024-01-08T09:00:00Z", "ms_played": 120_000},  # Mon, 7-12
        {"id": "3", "played_at": "2024-01-14T20:00:00Z", "ms_played": 180_000},  # Sun, 19-23
    ])
    rows = get_daily_activity_pattern(db)
    by_key = {(r["weekday"], r["segment"]): r["total_ms"] for r in rows}
    assert by_key[("Mon", "0-6")] == 60_000
    assert by_key[("Mon", "7-12")] == 120_000
    assert by_key[("Sun", "19-23")] == 180_000
    mon = next(r for r in rows if r["weekday"] == "Mon")
    sun = next(r for r in rows if r["weekday"] == "Sun")
    assert mon["weekday_idx"] == 0
    assert sun["weekday_idx"] == 6


def test_daily_activity_pattern_date_filter(tmp_path):
    db = str(tmp_path / "history.db")
    init_history_db(db)
    _seed(db, [
        {"id": "1", "played_at": "2024-01-08T03:00:00Z", "ms_played": 60_000},
        {"id": "2", "played_at": "2024-02-08T03:00:00Z", "ms_played": 60_000},
    ])
    rows = get_daily_activity_pattern(db, start_date="2024-02-01")
    assert sum(r["total_ms"] for r in rows) == 60_000


def test_daily_activity_pattern_empty_db(tmp_path):
    db = str(tmp_path / "empty.db")
    init_history_db(db)
    assert get_daily_activity_pattern(db) == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/core/test_chart_queries.py -v`
Expected: FAIL with `ImportError: cannot import name 'get_daily_activity_pattern'`.

- [ ] **Step 3: Add module constants**

In `packages/core/spotify_core/db/queries.py`, add these constants right after the
existing `_DOW_MAP` definition:

```python
# Short weekday names keyed by SQLite strftime('%w') (0 = Sunday).
_DOW_SHORT = {
    "0": "Sun", "1": "Mon", "2": "Tue", "3": "Wed",
    "4": "Thu", "5": "Fri", "6": "Sat",
}

# Stacking order for the daily-activity time segments.
_SEGMENT_ORDER = {"0-6": 0, "7-12": 1, "13-18": 2, "19-23": 3}
```

- [ ] **Step 4: Implement `get_daily_activity_pattern`**

Append this function to `packages/core/spotify_core/db/queries.py`:

```python
def get_daily_activity_pattern(
    db_path: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> list[dict]:
    """Per-weekday, per-time-segment listening volume from history.db.

    Timestamps are shifted to local time (offset inferred from conn_country)
    before grouping. Time segments are local hour-of-day ranges 0-6, 7-12,
    13-18, 19-23.

    Args:
        db_path: Path to history.db.
        start_date: ISO date string "YYYY-MM-DD" (inclusive, optional).
        end_date: ISO date string "YYYY-MM-DD" (inclusive, optional).

    Returns:
        List of {"weekday": str, "weekday_idx": int, "segment": str,
        "total_ms": int}, ordered by weekday (Mon..Sun) then segment.
    """
    _validate_date_range(start_date, end_date)
    _ensure_history_db(db_path)
    logger.debug("get_daily_activity_pattern: start=%s end=%s", start_date, end_date)
    date_clauses, params = _date_window(start_date, end_date)
    where_sql = ("WHERE " + " AND ".join(date_clauses)) if date_clauses else ""

    conn = get_connection(db_path)
    try:
        offset = _detect_tz_offset(conn)
        tz_mod = f"+{offset} hours" if offset >= 0 else f"{offset} hours"
        local_ts = f"datetime(played_at, '{tz_mod}')"
        hour_expr = f"CAST(strftime('%H', {local_ts}) AS INTEGER)"
        sql = f"""
            SELECT
                strftime('%w', {local_ts}) AS dow,
                CASE
                    WHEN {hour_expr} BETWEEN 0 AND 6 THEN '0-6'
                    WHEN {hour_expr} BETWEEN 7 AND 12 THEN '7-12'
                    WHEN {hour_expr} BETWEEN 13 AND 18 THEN '13-18'
                    ELSE '19-23'
                END AS segment,
                SUM(ms_played) AS total_ms
            FROM listening_history
            {where_sql}
            GROUP BY dow, segment
        """
        rows = conn.execute(sql, params).fetchall()
        result = []
        for r in rows:
            dow = r["dow"]  # '0'..'6', 0 = Sunday
            result.append({
                "weekday": _DOW_SHORT[dow],
                "weekday_idx": (int(dow) + 6) % 7,  # 0 = Mon .. 6 = Sun
                "segment": r["segment"],
                "total_ms": r["total_ms"] or 0,
            })
        result.sort(key=lambda d: (d["weekday_idx"], _SEGMENT_ORDER[d["segment"]]))
        logger.info("get_daily_activity_pattern: %d (weekday, segment) rows", len(result))
        return result
    except Exception:
        logger.exception("get_daily_activity_pattern failed: db_path=%s", db_path)
        raise
    finally:
        conn.close()
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/core/test_chart_queries.py::test_daily_activity_pattern_buckets tests/core/test_chart_queries.py::test_daily_activity_pattern_date_filter tests/core/test_chart_queries.py::test_daily_activity_pattern_empty_db -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add packages/core/spotify_core/db/queries.py tests/core/test_chart_queries.py
git commit -m "feat: add get_daily_activity_pattern query"
```

---

## Task 3: `_grouped_trend` helper and the three trend queries

Introduces the shared trend helper and all three trend queries — daily, weekly,
monthly — for Plot 2. Once `_grouped_trend` exists, the three public queries are
one-line wrappers that differ only in their `strftime` bucket expression, so they
are built and tested together rather than as separate tasks.

**Files:**
- Modify: `packages/core/spotify_core/db/queries.py`
- Test: `tests/core/test_chart_queries.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/core/test_chart_queries.py`:

```python
def test_daily_trend(tmp_path):
    db = str(tmp_path / "history.db")
    init_history_db(db)
    _seed(db, [
        {"id": "1", "played_at": "2024-01-08T03:00:00Z", "ms_played": 60_000},
        {"id": "2", "played_at": "2024-01-08T09:00:00Z", "ms_played": 120_000},
        {"id": "3", "played_at": "2024-01-09T09:00:00Z", "ms_played": 90_000},
    ])
    rows = get_daily_trend(db)
    assert rows == [
        {"date": "2024-01-08", "total_ms": 180_000, "play_count": 2},
        {"date": "2024-01-09", "total_ms": 90_000, "play_count": 1},
    ]


def test_daily_trend_date_filter(tmp_path):
    db = str(tmp_path / "history.db")
    init_history_db(db)
    _seed(db, [
        {"id": "1", "played_at": "2024-01-08T09:00:00Z", "ms_played": 60_000},
        {"id": "2", "played_at": "2024-02-08T09:00:00Z", "ms_played": 90_000},
    ])
    rows = get_daily_trend(db, end_date="2024-01-31")
    assert rows == [{"date": "2024-01-08", "total_ms": 60_000, "play_count": 1}]


def test_daily_trend_empty_db(tmp_path):
    db = str(tmp_path / "empty.db")
    init_history_db(db)
    assert get_daily_trend(db) == []


def test_weekly_trend(tmp_path):
    db = str(tmp_path / "history.db")
    init_history_db(db)
    _seed(db, [
        {"id": "1", "played_at": "2024-01-08T09:00:00Z", "ms_played": 60_000},
        {"id": "2", "played_at": "2024-02-08T09:00:00Z", "ms_played": 120_000},
    ])
    rows = get_weekly_trend(db)
    assert len(rows) == 2
    assert all({"week_label", "total_ms", "play_count"} <= set(r) for r in rows)
    assert rows[0]["week_label"] < rows[1]["week_label"]
    assert {r["total_ms"] for r in rows} == {60_000, 120_000}


def test_weekly_trend_empty_db(tmp_path):
    db = str(tmp_path / "empty.db")
    init_history_db(db)
    assert get_weekly_trend(db) == []


def test_monthly_trend(tmp_path):
    db = str(tmp_path / "history.db")
    init_history_db(db)
    _seed(db, [
        {"id": "1", "played_at": "2024-01-08T09:00:00Z", "ms_played": 60_000},
        {"id": "2", "played_at": "2024-01-20T09:00:00Z", "ms_played": 40_000},
        {"id": "3", "played_at": "2024-02-08T09:00:00Z", "ms_played": 120_000},
    ])
    rows = get_monthly_trend(db)
    assert rows == [
        {"month_label": "2024-01", "total_ms": 100_000, "play_count": 2},
        {"month_label": "2024-02", "total_ms": 120_000, "play_count": 1},
    ]


def test_monthly_trend_empty_db(tmp_path):
    db = str(tmp_path / "empty.db")
    init_history_db(db)
    assert get_monthly_trend(db) == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/core/test_chart_queries.py -k "trend" -v`
Expected: FAIL with `ImportError: cannot import name 'get_daily_trend'`.

- [ ] **Step 3: Implement `_grouped_trend` and the three trend queries**

Append to `packages/core/spotify_core/db/queries.py`:

```python
def _grouped_trend(
    db_path: str,
    start_date: Optional[str],
    end_date: Optional[str],
    group_expr: str,
    label_key: str,
) -> list[dict]:
    """Sum ms_played and count plays grouped by a strftime bucket on local time.

    Args:
        db_path: Path to history.db.
        start_date: ISO date string "YYYY-MM-DD" (inclusive, optional).
        end_date: ISO date string "YYYY-MM-DD" (inclusive, optional).
        group_expr: A SQL expression template with a "{ts}" placeholder for the
            local-timestamp expression, e.g. "date({ts})".
        label_key: Dict key under which the bucket label is returned.

    Returns:
        List of {label_key: str, "total_ms": int, "play_count": int}, ordered
        by bucket ascending.
    """
    _validate_date_range(start_date, end_date)
    _ensure_history_db(db_path)
    date_clauses, params = _date_window(start_date, end_date)
    where_sql = ("WHERE " + " AND ".join(date_clauses)) if date_clauses else ""

    conn = get_connection(db_path)
    try:
        offset = _detect_tz_offset(conn)
        tz_mod = f"+{offset} hours" if offset >= 0 else f"{offset} hours"
        local_ts = f"datetime(played_at, '{tz_mod}')"
        bucket_expr = group_expr.format(ts=local_ts)
        sql = f"""
            SELECT {bucket_expr} AS bucket,
                   SUM(ms_played) AS total_ms,
                   COUNT(*) AS play_count
            FROM listening_history
            {where_sql}
            GROUP BY bucket
            ORDER BY bucket
        """
        rows = conn.execute(sql, params).fetchall()
        result = [
            {label_key: r["bucket"], "total_ms": r["total_ms"] or 0,
             "play_count": r["play_count"]}
            for r in rows
        ]
        logger.info("_grouped_trend(%s): %d buckets", label_key, len(result))
        return result
    except Exception:
        logger.exception("_grouped_trend failed: db_path=%s key=%s", db_path, label_key)
        raise
    finally:
        conn.close()


def get_daily_trend(
    db_path: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> list[dict]:
    """Per-calendar-day listening totals (local date) from history.db.

    Returns:
        List of {"date": "YYYY-MM-DD", "total_ms": int, "play_count": int},
        ordered by date ascending.
    """
    return _grouped_trend(db_path, start_date, end_date, "date({ts})", "date")


def get_weekly_trend(
    db_path: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> list[dict]:
    """Per-ISO-week listening totals (Monday-based) from history.db.

    Returns:
        List of {"week_label": "YYYY-WNN", "total_ms": int, "play_count": int},
        ordered by week ascending.
    """
    return _grouped_trend(
        db_path, start_date, end_date, "strftime('%Y-W%W', {ts})", "week_label"
    )


def get_monthly_trend(
    db_path: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> list[dict]:
    """Per-month listening totals from history.db.

    Returns:
        List of {"month_label": "YYYY-MM", "total_ms": int, "play_count": int},
        ordered by month ascending.
    """
    return _grouped_trend(
        db_path, start_date, end_date, "strftime('%Y-%m', {ts})", "month_label"
    )
```

- [ ] **Step 4: Run the full chart-query suite**

Run: `uv run pytest tests/core/test_chart_queries.py -v`
Expected: PASS (all tests across Tasks 2–3).

- [ ] **Step 5: Commit**

```bash
git add packages/core/spotify_core/db/queries.py tests/core/test_chart_queries.py
git commit -m "feat: add _grouped_trend helper and daily/weekly/monthly trend queries"
```

---

> **Tasks 4–6 are independent** — `formatting.py`, `config.py`, and `charts.py` have
> no cross-dependencies and each modifies a disjoint file set. When using
> `subagent-driven-development`, they can be dispatched in parallel.

## Task 4: Formatting helpers (`spotify_web/formatting.py`)

Pure helpers: Spotify URI → open.spotify.com URL, and millisecond duration → human string.

**Files:**
- Create: `apps/web/spotify_web/formatting.py`
- Create: `tests/web/__init__.py`
- Test: `tests/web/test_formatting.py`

- [ ] **Step 1: Create the test package marker and the failing test**

Create `tests/web/__init__.py` as an empty file.

Create `tests/web/test_formatting.py`:

```python
"""Tests for spotify_web.formatting."""
from spotify_web.formatting import spotify_uri_to_url, format_duration_ms


def test_uri_to_url_valid():
    assert spotify_uri_to_url("spotify:track:abc123") == \
        "https://open.spotify.com/track/abc123"


def test_uri_to_url_none():
    assert spotify_uri_to_url(None) is None


def test_uri_to_url_empty_string():
    assert spotify_uri_to_url("") is None


def test_uri_to_url_non_track():
    assert spotify_uri_to_url("spotify:episode:xyz789") is None


def test_uri_to_url_empty_track_id():
    assert spotify_uri_to_url("spotify:track:") is None


def test_format_duration_zero():
    assert format_duration_ms(0) == "0m"


def test_format_duration_none():
    assert format_duration_ms(None) == "0m"


def test_format_duration_minutes_only():
    assert format_duration_ms(45 * 60_000) == "45m"


def test_format_duration_hours_and_minutes():
    assert format_duration_ms((3 * 60 + 12) * 60_000) == "3h 12m"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/web/test_formatting.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'spotify_web.formatting'`.

- [ ] **Step 3: Implement `formatting.py`**

Create `apps/web/spotify_web/formatting.py`:

```python
"""Pure formatting helpers for the dashboard UI."""
from typing import Optional


def spotify_uri_to_url(uri: Optional[str]) -> Optional[str]:
    """Convert a 'spotify:track:<id>' URI to an open.spotify.com track URL.

    Returns None for empty values or any URI that is not a non-empty track URI
    (e.g. podcast-episode URIs).
    """
    if not uri or not uri.startswith("spotify:track:"):
        return None
    track_id = uri.split(":", 2)[2]
    if not track_id:
        return None
    return f"https://open.spotify.com/track/{track_id}"


def format_duration_ms(ms: Optional[int]) -> str:
    """Format a millisecond duration as a human string, e.g. '3h 12m' or '45m'."""
    if not ms or ms < 0:
        return "0m"
    total_minutes = ms // 60_000
    hours, minutes = divmod(total_minutes, 60)
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/web/test_formatting.py -v`
Expected: PASS (9 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/web/spotify_web/formatting.py tests/web/__init__.py tests/web/test_formatting.py
git commit -m "feat: add spotify_web formatting helpers"
```

---

## Task 5: Sync-credential resolver (`spotify_web/config.py`)

Resolves the keyword arguments for `sync_api_to_db`, mirroring
`apps/mcp/spotify_mcp/config.py`.

**Files:**
- Create: `apps/web/spotify_web/config.py`
- Test: `tests/web/test_web_config.py`

- [ ] **Step 1: Write the failing test**

Create `tests/web/test_web_config.py`:

```python
"""Tests for spotify_web.config sync-credential resolution."""
from spotify_web import config as web_config


def test_get_client_id_reads_env(monkeypatch):
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "cid-123")
    assert web_config.get_client_id() == "cid-123"


def test_get_client_id_missing(monkeypatch):
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    assert web_config.get_client_id() == ""


def test_get_fernet_key_reads_env(monkeypatch):
    monkeypatch.setenv("TOKEN_ENCRYPT_KEY", "k-abc")
    assert web_config.get_fernet_key() == b"k-abc"


def test_get_fernet_key_missing(monkeypatch):
    monkeypatch.delenv("TOKEN_ENCRYPT_KEY", raising=False)
    assert web_config.get_fernet_key() == b""


def test_get_sync_args_shape(monkeypatch):
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "cid")
    monkeypatch.setenv("TOKEN_ENCRYPT_KEY", "key")
    args = web_config.get_sync_args()
    assert set(args) == {
        "db_path", "tokens_db_path", "user_id", "client_id", "fernet_key",
    }
    assert args["client_id"] == "cid"
    assert args["fernet_key"] == b"key"
    assert isinstance(args["db_path"], str)
    assert isinstance(args["tokens_db_path"], str)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/web/test_web_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'spotify_web.config'`.

- [ ] **Step 3: Implement `config.py`**

Create `apps/web/spotify_web/config.py`:

```python
"""Sync-credential resolution for the dashboard's Sync button.

Mirrors apps/mcp/spotify_mcp/config.py: SPOTIFY_CLIENT_ID and TOKEN_ENCRYPT_KEY
are read from the environment (after loading the platformdirs .env), while the
DB paths and user id come from spotify_core.config.settings.
"""
import os

from dotenv import load_dotenv

from spotify_core import paths
from spotify_core.config import settings

# Platformdirs .env wins; a cwd .env is a dev-convenience fallback only.
if paths.env_file().exists():
    load_dotenv(paths.env_file())
load_dotenv(override=False)


def get_client_id() -> str:
    """Read SPOTIFY_CLIENT_ID from the environment at call time."""
    return os.getenv("SPOTIFY_CLIENT_ID", "")


def get_fernet_key() -> bytes:
    """Read TOKEN_ENCRYPT_KEY from the environment at call time, as bytes."""
    raw = os.getenv("TOKEN_ENCRYPT_KEY", "")
    return raw.encode() if raw else b""


def get_sync_args() -> dict:
    """Return the keyword arguments for spotify_core.db.pipeline.sync_api_to_db."""
    return {
        "db_path": str(settings.history_db_path),
        "tokens_db_path": str(settings.tokens_db_path),
        "user_id": settings.spotify_user_id,
        "client_id": get_client_id(),
        "fernet_key": get_fernet_key(),
    }
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/web/test_web_config.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/web/spotify_web/config.py tests/web/test_web_config.py
git commit -m "feat: add spotify_web sync-credential resolver"
```

---

## Task 6: Plotly figure builders (`spotify_web/charts.py`)

Pure `data → plotly.graph_objects.Figure` functions for Plot 1 and Plot 2.

**Files:**
- Create: `apps/web/spotify_web/charts.py`
- Test: `tests/web/test_charts.py`

- [ ] **Step 1: Write the failing test**

Create `tests/web/test_charts.py`:

```python
"""Tests for spotify_web.charts figure builders."""
from spotify_web.charts import daily_activity_figure, trend_figure


def test_daily_activity_figure_empty():
    fig = daily_activity_figure([])
    # One stacked-bar trace per time segment.
    assert len(fig.data) == 4


def test_daily_activity_figure_values():
    rows = [
        {"weekday": "Mon", "weekday_idx": 0, "segment": "7-12", "total_ms": 600_000},
    ]
    fig = daily_activity_figure(rows)
    seg_trace = next(t for t in fig.data if t.name == "7-12")
    # Mon is the first weekday; 600_000 ms = 10 minutes.
    assert seg_trace.y[0] == 10
    assert tuple(seg_trace.x) == ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def test_trend_figure_values():
    rows = [{"date": "2024-01-01", "total_ms": 600_000, "play_count": 3}]
    fig = trend_figure(rows, "date", "daily")
    assert len(fig.data) == 1
    assert tuple(fig.data[0].x) == ("2024-01-01",)
    assert tuple(fig.data[0].y) == (10,)


def test_trend_figure_empty():
    fig = trend_figure([], "week_label", "weekly")
    assert len(fig.data) == 1
    assert tuple(fig.data[0].x) == ()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/web/test_charts.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'spotify_web.charts'`.

- [ ] **Step 3: Implement `charts.py`**

Create `apps/web/spotify_web/charts.py`:

```python
"""Plotly figure builders for the dashboard. Pure: data in, Figure out."""
import plotly.graph_objects as go

_SEGMENT_ORDER = ["0-6", "7-12", "13-18", "19-23"]
_SEGMENT_COLORS = {
    "0-6":   "rgba(31, 96, 180, 0.9)",
    "7-12":  "rgba(231, 185, 0, 0.9)",
    "13-18": "rgba(255, 126, 14, 0.9)",
    "19-23": "rgba(214, 39, 39, 0.85)",
}
_WEEKDAY_ORDER = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_TREND_TITLES = {
    "daily": "Daily Listening",
    "weekly": "Weekly Listening",
    "monthly": "Monthly Listening",
}


def daily_activity_figure(rows: list[dict]) -> go.Figure:
    """Build the Plot 1 stacked bar: x = Mon..Sun, y = minutes, stacked by segment.

    Args:
        rows: Output of queries.get_daily_activity_pattern — dicts with
            "weekday", "weekday_idx", "segment", "total_ms".
    """
    fig = go.Figure()
    for segment in _SEGMENT_ORDER:
        minutes_by_day = {
            r["weekday"]: round((r["total_ms"] or 0) / 60_000)
            for r in rows
            if r["segment"] == segment
        }
        fig.add_bar(
            name=segment,
            x=_WEEKDAY_ORDER,
            y=[minutes_by_day.get(day, 0) for day in _WEEKDAY_ORDER],
            marker_color=_SEGMENT_COLORS[segment],
        )
    fig.update_layout(
        barmode="stack",
        xaxis_title="",
        yaxis_title="Minutes",
        legend_title="Time segment",
        height=420,
    )
    return fig


def trend_figure(rows: list[dict], label_key: str, granularity: str) -> go.Figure:
    """Build the Plot 2 bar chart of listening minutes per time bucket.

    Args:
        rows: Output of queries.get_daily/weekly/monthly_trend.
        label_key: Dict key holding the bucket label ("date" / "week_label" /
            "month_label").
        granularity: "daily" | "weekly" | "monthly" — used for the chart title.
    """
    fig = go.Figure(
        go.Bar(
            x=[r[label_key] for r in rows],
            y=[round((r["total_ms"] or 0) / 60_000) for r in rows],
            marker_color="rgba(30, 160, 90, 0.85)",
        )
    )
    fig.update_layout(
        title=_TREND_TITLES.get(granularity, "Listening Trend"),
        xaxis_title="",
        yaxis_title="Minutes",
        height=420,
    )
    return fig
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/web/test_charts.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/web/spotify_web/charts.py tests/web/test_charts.py
git commit -m "feat: add spotify_web Plotly figure builders"
```

---

## Task 7: Rewrite the Streamlit UI

Rewrites the three `apps/web/ui/` pages — the DB-backed dashboard, the chat
placeholder, and the slim navigation shell — and deletes the now-unused
Polars-based files and the agent/loader session module. `main_page.py` imports
both other pages, so they are rewritten and verified together; the single
`streamlit run` smoke-test at the end covers the whole UI. Streamlit render is
not unit-tested per spec §10.

**Files:**
- Rewrite: `apps/web/ui/dashboard.py`
- Rewrite: `apps/web/ui/chatbot_page.py`
- Rewrite: `apps/web/ui/main_page.py`
- Delete: `apps/web/ui/time_analysis.py`
- Delete: `apps/web/ui/track_analysis.py`
- Delete: `apps/web/spotify_web/session.py`

- [ ] **Step 1: Replace `dashboard.py` with the DB-backed implementation**

Overwrite `apps/web/ui/dashboard.py` with:

```python
"""DB-backed analytics dashboard (Streamlit page)."""
import datetime
import logging

import streamlit as st

from spotify_core.config import settings
from spotify_core.db.pipeline import sync_api_to_db
from spotify_core.db.queries import (
    get_daily_activity_pattern,
    get_daily_trend,
    get_listening_summary,
    get_monthly_trend,
    get_recent_plays,
    get_top_artists,
    get_top_tracks,
    get_weekly_trend,
    is_history_empty,
)
from spotify_web.charts import daily_activity_figure, trend_figure
from spotify_web.config import get_sync_args
from spotify_web.formatting import format_duration_ms, spotify_uri_to_url

logger = logging.getLogger(__name__)

_DB_PATH = str(settings.history_db_path)
_CACHE_TTL = 30  # seconds; also cleared explicitly after a sync


@st.cache_data(ttl=_CACHE_TTL)
def _summary(start, end):
    return get_listening_summary(_DB_PATH, start_date=start, end_date=end)


@st.cache_data(ttl=_CACHE_TTL)
def _top_artists(start, end):
    return get_top_artists(_DB_PATH, limit=5, start_date=start, end_date=end)


@st.cache_data(ttl=_CACHE_TTL)
def _top_tracks(start, end):
    return get_top_tracks(
        _DB_PATH, limit=5, start_date=start, end_date=end, show_track_id=True
    )


@st.cache_data(ttl=_CACHE_TTL)
def _activity(start, end):
    return get_daily_activity_pattern(_DB_PATH, start_date=start, end_date=end)


@st.cache_data(ttl=_CACHE_TTL)
def _daily(start, end):
    return get_daily_trend(_DB_PATH, start_date=start, end_date=end)


@st.cache_data(ttl=_CACHE_TTL)
def _weekly(start, end):
    return get_weekly_trend(_DB_PATH, start_date=start, end_date=end)


@st.cache_data(ttl=_CACHE_TTL)
def _monthly(start, end):
    return get_monthly_trend(_DB_PATH, start_date=start, end_date=end)


@st.cache_data(ttl=_CACHE_TTL)
def _recent():
    return get_recent_plays(_DB_PATH, limit=50, show_track_id=True)


def _period_dates() -> tuple[str, str]:
    """Render the period filter; return (start_iso, end_iso) date strings."""
    today = datetime.date.today()
    choice = st.radio(
        "分析區間",
        ["本周", "本月", "自訂時間"],
        horizontal=True,
        key="period_choice",
    )
    if choice == "本周":
        start = today - datetime.timedelta(days=today.weekday())  # Monday
        end = today
    elif choice == "本月":
        start = today.replace(day=1)
        end = today
    else:
        c1, c2 = st.columns(2)
        start = c1.date_input(
            "開始", value=today - datetime.timedelta(days=30), key="custom_start"
        )
        end = c2.date_input("結束", value=today, key="custom_end")
    return start.isoformat(), end.isoformat()


def _run_sync() -> None:
    """Pull recent plays from the Spotify API into the local DB."""
    args = get_sync_args()
    if not args["client_id"] or not args["fernet_key"]:
        st.error(
            "缺少 SPOTIFY_CLIENT_ID 或 TOKEN_ENCRYPT_KEY，請先執行 `spotify-mcp setup`。"
        )
        return
    try:
        result = sync_api_to_db(**args)
        st.cache_data.clear()
        st.toast(f"已同步 {result['inserted']} 筆新播放紀錄")
    except RuntimeError as exc:
        st.error(f"同步失敗：{exc}")
    except Exception as exc:  # noqa: BLE001 - surface any sync error in the UI
        logger.exception("Dashboard sync failed")
        st.error(f"同步時發生錯誤：{exc}")


def _stats_section(start: str, end: str) -> None:
    st.subheader("Top Stats")
    col_a, col_t = st.columns(2)
    with col_a:
        st.caption("Top 5 Artists — by listening time")
        artists = _top_artists(start, end)
        if artists:
            st.dataframe(
                [
                    {
                        "Artist": a["artist_name"],
                        "Listening time": format_duration_ms(a["total_ms"]),
                    }
                    for a in artists
                ],
                hide_index=True,
                width="stretch",
            )
        else:
            st.info("此區間沒有資料。")
    with col_t:
        st.caption("Top 5 Tracks — by play count")
        tracks = _top_tracks(start, end)
        if tracks:
            st.dataframe(
                [
                    {
                        "Track": t["track_name"],
                        "Artist": t["artist_name"],
                        "Plays": t["play_count"],
                        "Spotify": spotify_uri_to_url(t.get("track_id")),
                    }
                    for t in tracks
                ],
                column_config={
                    "Spotify": st.column_config.LinkColumn(
                        "Spotify", display_text="▶ Open"
                    )
                },
                hide_index=True,
                width="stretch",
            )
        else:
            st.info("此區間沒有資料。")


def _trend_section(start: str, end: str) -> None:
    """Render Plot 2, picking granularity from the period span."""
    days = (
        datetime.date.fromisoformat(end) - datetime.date.fromisoformat(start)
    ).days + 1
    if days <= 14:
        rows, label_key, gran = _daily(start, end), "date", "daily"
    elif days <= 92:
        rows, label_key, gran = _weekly(start, end), "week_label", "weekly"
    else:
        rows, label_key, gran = _monthly(start, end), "month_label", "monthly"
    if rows:
        st.plotly_chart(trend_figure(rows, label_key, gran), width="stretch")
    else:
        st.info("此區間沒有資料。")


def _recent_section() -> None:
    st.subheader("Recently Played (last 50)")
    rows = _recent()
    if not rows:
        st.info("資料庫沒有播放紀錄。")
        return
    st.dataframe(
        [
            {
                "Played at": r["played_at"],
                "Track": r["track_name"],
                "Artist": r["artist_name"],
                "Album": r["album_name"],
                "Spotify": spotify_uri_to_url(r.get("track_id")),
            }
            for r in rows
        ],
        column_config={
            "Spotify": st.column_config.LinkColumn("Spotify", display_text="▶ Open")
        },
        hide_index=True,
        width="stretch",
    )


def render_dashboard() -> None:
    st.subheader("📊 Dashboard")

    col_filter, col_sync = st.columns([4, 1], vertical_alignment="bottom")
    with col_sync:
        if st.button("🔄 Sync", width="stretch"):
            _run_sync()
    with col_filter:
        start, end = _period_dates()

    if is_history_empty(_DB_PATH):
        st.warning(
            "資料庫沒有資料。請執行 `spotify-mcp setup` 匯入歷史，"
            "或點右上 Sync 取得最近 50 筆播放。"
        )
        return

    summary = _summary(start, end)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Plays", f"{summary['total_plays']:,}")
    m2.metric("Listening time", format_duration_ms(summary["total_ms_played"]))
    m3.metric("Unique artists", f"{summary['unique_artists'] or 0:,}")
    m4.metric("Unique tracks", f"{summary['unique_tracks'] or 0:,}")

    st.divider()
    _stats_section(start, end)

    st.divider()
    st.subheader("Daily Activity Pattern")
    activity = _activity(start, end)
    if activity:
        st.plotly_chart(daily_activity_figure(activity), width="stretch")
    else:
        st.info("此區間沒有資料。")

    st.subheader("Listening Trend")
    _trend_section(start, end)

    st.divider()
    _recent_section()
```

- [ ] **Step 2: Replace `chatbot_page.py` with the placeholder**

Overwrite `apps/web/ui/chatbot_page.py` with:

```python
"""Chat page — placeholder.

# TODO: replace with the Chainlit-based agent chat. See
# docs/superpowers/specs/2026-05-15-chatbot-platform-roadmap.md (section 2.2).
"""
import streamlit as st


def render_chatbot() -> None:
    st.subheader("💬 Chat")
    st.info("Chat is under construction.")
```

- [ ] **Step 3: Replace `main_page.py` with the slim shell**

Overwrite `apps/web/ui/main_page.py` with:

```python
"""Streamlit entry point: navigation shell for the dashboard and chat pages."""
import streamlit as st

from spotify_core.config import settings
from spotify_core.logging import setup_logging

from chatbot_page import render_chatbot
from dashboard import render_dashboard

setup_logging()
st.set_page_config(layout="wide", page_title="Spotify Analytics", page_icon="🎵")


def main() -> None:
    st.title("Spotify Analytics")

    with st.sidebar:
        st.header("Navigation")
        page = st.radio("View", ["Dashboard", "Chat"], key="nav_radio")
        st.divider()
        st.caption(f"Database: {settings.history_db_path}")

    if page == "Dashboard":
        render_dashboard()
    else:
        render_chatbot()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Confirm `spotify_web/session.py` has no remaining importers**

Run: `uv run python -c "import subprocess; print(subprocess.run(['git','grep','-n','session'], capture_output=True, text=True).stdout)"`
Expected: no `import session` / `from session` / `spotify_web.session` references in
`apps/web/` outside `session.py` itself. (Steps 1–3 removed the only importers —
`main_page.py`, `chatbot_page.py`, `dashboard.py`.)

- [ ] **Step 5: Delete the superseded files**

```bash
git rm apps/web/ui/time_analysis.py apps/web/ui/track_analysis.py apps/web/spotify_web/session.py
```

- [ ] **Step 6: Smoke-test the app launch**

Run: `uv run streamlit run apps/web/ui/main_page.py --server.headless true`
Expected: Streamlit starts with no import error and prints a local URL. Open the URL,
confirm the Dashboard renders (metrics, stats, two plots, recent table) and the Chat
tab shows the "under construction" message. Stop the server with Ctrl+C.

- [ ] **Step 7: Commit**

```bash
git add apps/web/ui/dashboard.py apps/web/ui/chatbot_page.py apps/web/ui/main_page.py
git commit -m "feat: rewrite web app as DB-backed dashboard + chat placeholder"
```

---

## Task 8: Add the `run_dashboard.bat` launcher and run full regression

Repo-root launcher that gates startup on `spotify-mcp doctor` and runs the setup
wizard when setup is incomplete, followed by the final full-suite regression run.

**Files:**
- Create: `run_dashboard.bat`

- [ ] **Step 1: Create `run_dashboard.bat`**

Create `run_dashboard.bat` at the repository root:

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

- [ ] **Step 2: Verify the doctor command resolves**

Run: `uv run spotify-mcp doctor`
Expected: prints a JSON readiness report. Exit code 0 when setup is complete, 1
otherwise — either is fine; this step only confirms the `spotify-mcp` CLI is
reachable via `uv run`.

- [ ] **Step 3: Smoke-test the launcher**

Double-click `run_dashboard.bat` (or run it from a terminal). Expected: if setup is
complete the dashboard opens in the browser; if not, the setup wizard runs first.
Stop the server with Ctrl+C when done.

- [ ] **Step 4: Commit**

```bash
git add run_dashboard.bat
git commit -m "chore: add run_dashboard.bat launcher"
```

- [ ] **Step 5: Run the whole test suite**

Run: `uv run pytest -q`
Expected: PASS — including `tests/core/test_queries.py` (Task 1 regression),
`tests/core/test_chart_queries.py` (Tasks 2–3), and `tests/web/` (Tasks 4–6). No
new failures versus the pre-existing baseline.

- [ ] **Step 6: If any pre-existing unrelated test was already failing before this work**

Note it in the final report; do not attempt to fix unrelated failures as part of
this plan.

---

## Self-Review Notes

**Spec coverage:**
- §3 new queries → Tasks 1–3 (`_date_window`, `get_daily_activity_pattern`,
  `_grouped_trend`, `get_daily_trend`, `get_weekly_trend`, `get_monthly_trend`).
- §3 targeted refactor (`_date_window`) → Task 1.
- §4 UI restructure → Tasks 4–8 (charts/formatting/config in `spotify_web`;
  `dashboard.py`, `chatbot_page.py`, `main_page.py` rewritten; `session.py`,
  `time_analysis.py`, `track_analysis.py` deleted).
- §5 dashboard layout (period filter, summary, stats, Plot 1, Plot 2 three-tier,
  recent 50, URI→URL, caching) → Tasks 6–7.
- §6 sync button → Tasks 5 + 7 (`get_sync_args`, `_run_sync`).
- §7 launcher → Task 8.
- §8 chat placeholder → Task 7.
- §9 error / empty-state handling → Task 7 (`is_history_empty` gate, per-section
  `st.info`, sync `try/except`).
- §10 testing → Tasks 2–6 (TDD) + Task 8 (full run); Streamlit render verified
  manually in Task 7.
- §11 roadmap update → already completed in the brainstorming session (not a task).

**Type consistency:** the query return keys (`weekday`, `weekday_idx`, `segment`,
`total_ms`, `date`, `week_label`, `month_label`, `play_count`) are used identically
by `charts.py` (`label_key` argument) and `dashboard.py` (`_trend_section` passes
`"date"`/`"week_label"`/`"month_label"` matching Task 3). `get_sync_args` returns
exactly the five `sync_api_to_db` keyword arguments.
