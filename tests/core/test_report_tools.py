"""Tests for spotify_core.report.tools — the drafter's data tools."""
from spotify_core.db.migrations import get_connection, init_history_db
from spotify_core.report.tools import make_report_tools


def _seed(db_path, rows):
    """Insert minimal listening_history rows for tool tests."""
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


def _tools(db_path):
    return {t.name: t for t in make_report_tools(db_path)}


def test_make_report_tools_names(tmp_path):
    db = str(tmp_path / "history.db")
    init_history_db(db)
    assert set(_tools(db)) == {
        "get_listening_summary", "get_top_artists", "get_top_tracks",
        "get_daily_activity_pattern", "get_daily_trend", "get_weekly_trend",
        "get_monthly_trend",
    }


def test_top_artists_tool_returns_rows(tmp_path):
    db = str(tmp_path / "history.db")
    init_history_db(db)
    _seed(db, [
        {"id": "1", "played_at": "2024-01-08T09:00:00Z", "ms_played": 200_000,
         "artist_name": "Radiohead"},
        {"id": "2", "played_at": "2024-01-09T09:00:00Z", "ms_played": 100_000,
         "artist_name": "Radiohead"},
    ])
    rows = _tools(db)["get_top_artists"].invoke(
        {"start_date": "2024-01-01", "end_date": "2024-01-31"}
    )
    assert rows[0]["artist_name"] == "Radiohead"
    assert rows[0]["total_ms"] == 300_000


def test_trend_tools_return_expected_keys(tmp_path):
    db = str(tmp_path / "history.db")
    init_history_db(db)
    _seed(db, [
        {"id": "1", "played_at": "2024-01-08T09:00:00Z", "ms_played": 60_000},
        {"id": "2", "played_at": "2024-03-08T09:00:00Z", "ms_played": 90_000},
    ])
    tools = _tools(db)
    rng = {"start_date": "2024-01-01", "end_date": "2024-12-31"}
    daily = tools["get_daily_trend"].invoke(rng)
    weekly = tools["get_weekly_trend"].invoke(rng)
    monthly = tools["get_monthly_trend"].invoke(rng)
    assert daily and all("date" in r for r in daily)
    assert weekly and all("week_label" in r for r in weekly)
    assert monthly and all("month_label" in r for r in monthly)


def test_summary_tool_date_passthrough(tmp_path):
    db = str(tmp_path / "history.db")
    init_history_db(db)
    _seed(db, [
        {"id": "1", "played_at": "2024-01-08T09:00:00Z", "ms_played": 60_000},
        {"id": "2", "played_at": "2024-03-08T09:00:00Z", "ms_played": 60_000},
    ])
    summary = _tools(db)["get_listening_summary"].invoke(
        {"start_date": "2024-01-01", "end_date": "2024-01-31"}
    )
    assert summary["total_plays"] == 1
