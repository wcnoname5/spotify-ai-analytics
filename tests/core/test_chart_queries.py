"""Tests for the dashboard chart queries in db/queries.py."""
import re
import sqlite3

import pytest

from spotify_core.db import queries
from spotify_core.db.queries import (
    _tz_modifier,
    get_daily_activity_pattern,
    get_daily_trend,
    get_weekly_trend,
    get_monthly_trend,
)


@pytest.fixture(autouse=True)
def _utc(monkeypatch):
    """Pin local time to UTC so bucket assertions don't depend on the machine's zone."""
    monkeypatch.setattr(queries, "_tz_modifier", lambda: "+0 hours")


def test_tz_modifier_is_a_valid_sqlite_modifier():
    mod = _tz_modifier()
    assert re.fullmatch(r"[+-]\d+(\.\d+)? hours", mod)
    with sqlite3.connect(":memory:") as conn:
        assert conn.execute("SELECT datetime('2024-01-01T00:00:00Z', ?)", (mod,)).fetchone()[0]


def test_buckets_follow_the_local_offset(history_db, monkeypatch):
    db = history_db([{"id": "1", "played_at": "2024-01-08T20:00:00Z", "ms_played": 60_000}])
    monkeypatch.setattr(queries, "_tz_modifier", lambda: "+8 hours")
    assert get_daily_trend(db) == [{"date": "2024-01-09", "total_mins": 1, "play_count": 1}]


def test_daily_activity_pattern_buckets(history_db):
    db = history_db([
        {"id": "1", "played_at": "2024-01-08T03:00:00Z", "ms_played": 60_000},   # Monday, 00:00-06:59
        {"id": "2", "played_at": "2024-01-08T09:00:00Z", "ms_played": 120_000},  # Monday, 07:00-12:59
        {"id": "3", "played_at": "2024-01-14T20:00:00Z", "ms_played": 180_000},  # Sunday, 19:00-23:59
    ])
    rows = get_daily_activity_pattern(db)
    by_key = {(r["weekday"], r["segment"]): r["total_mins"] for r in rows}
    assert by_key[("Monday", "00:00-06:59")] == 1
    assert by_key[("Monday", "07:00-12:59")] == 2
    assert by_key[("Sunday", "19:00-23:59")] == 3
    mon = next(r for r in rows if r["weekday"] == "Monday")
    sun = next(r for r in rows if r["weekday"] == "Sunday")
    assert mon["weekday_idx"] == 0
    assert sun["weekday_idx"] == 6


def test_daily_activity_pattern_date_filter(history_db):
    db = history_db([
        {"id": "1", "played_at": "2024-01-08T03:00:00Z", "ms_played": 60_000},
        {"id": "2", "played_at": "2024-02-08T03:00:00Z", "ms_played": 60_000},
    ])
    rows = get_daily_activity_pattern(db, start_date="2024-02-01")
    assert sum(r["total_mins"] for r in rows) == 1


def test_daily_activity_pattern_empty_db(history_db):
    assert get_daily_activity_pattern(history_db()) == []


def test_daily_trend(history_db):
    db = history_db([
        {"id": "1", "played_at": "2024-01-08T03:00:00Z", "ms_played": 60_000},
        {"id": "2", "played_at": "2024-01-08T09:00:00Z", "ms_played": 120_000},
        {"id": "3", "played_at": "2024-01-09T09:00:00Z", "ms_played": 90_000},
    ])
    rows = get_daily_trend(db)
    assert rows == [
        {"date": "2024-01-08", "total_mins": 3, "play_count": 2},
        {"date": "2024-01-09", "total_mins": 1, "play_count": 1},
    ]


def test_daily_trend_date_filter(history_db):
    db = history_db([
        {"id": "1", "played_at": "2024-01-08T09:00:00Z", "ms_played": 60_000},
        {"id": "2", "played_at": "2024-02-08T09:00:00Z", "ms_played": 90_000},
    ])
    rows = get_daily_trend(db, end_date="2024-01-31")
    assert rows == [{"date": "2024-01-08", "total_mins": 1, "play_count": 1}]


def test_daily_trend_empty_db(history_db):
    assert get_daily_trend(history_db()) == []


def test_weekly_trend(history_db):
    db = history_db([
        {"id": "1", "played_at": "2024-01-08T09:00:00Z", "ms_played": 60_000},
        {"id": "2", "played_at": "2024-02-08T09:00:00Z", "ms_played": 120_000},
    ])
    rows = get_weekly_trend(db)
    assert len(rows) == 2
    assert all({"week_label", "total_mins", "play_count"} <= set(r) for r in rows)
    assert rows[0]["week_label"] < rows[1]["week_label"]
    assert {r["total_mins"] for r in rows} == {1, 2}


def test_weekly_trend_empty_db(history_db):
    assert get_weekly_trend(history_db()) == []


def test_monthly_trend(history_db):
    db = history_db([
        {"id": "1", "played_at": "2024-01-08T09:00:00Z", "ms_played": 60_000},
        {"id": "2", "played_at": "2024-01-20T09:00:00Z", "ms_played": 40_000},
        {"id": "3", "played_at": "2024-02-08T09:00:00Z", "ms_played": 120_000},
    ])
    rows = get_monthly_trend(db)
    assert rows == [
        {"month_label": "2024-01", "total_mins": 1, "play_count": 2},
        {"month_label": "2024-02", "total_mins": 2, "play_count": 1},
    ]


def test_monthly_trend_empty_db(history_db):
    assert get_monthly_trend(history_db()) == []
