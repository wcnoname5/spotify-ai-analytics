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
        {"id": "1", "played_at": "2024-01-08T03:00:00Z", "ms_played": 60_000},   # Monday, 0-6
        {"id": "2", "played_at": "2024-01-08T09:00:00Z", "ms_played": 120_000},  # Monday, 7-12
        {"id": "3", "played_at": "2024-01-14T20:00:00Z", "ms_played": 180_000},  # Sunday, 19-23
    ])
    rows = get_daily_activity_pattern(db)
    by_key = {(r["weekday"], r["segment"]): r["total_ms"] for r in rows}
    assert by_key[("Monday", "0-6")] == 60_000
    assert by_key[("Monday", "7-12")] == 120_000
    assert by_key[("Sunday", "19-23")] == 180_000
    mon = next(r for r in rows if r["weekday"] == "Monday")
    sun = next(r for r in rows if r["weekday"] == "Sunday")
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
