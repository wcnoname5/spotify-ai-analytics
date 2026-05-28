"""Tests for shared Streamlit period filter helpers."""
import datetime

from spotify_web.period_filter import resolve_period_dates


def test_resolve_period_dates_last_completed_week():
    # Thursday 2026-05-21 → last completed week is Mon 05-11 ~ Sun 05-17.
    today = datetime.date(2026, 5, 21)

    start, end = resolve_period_dates("上週", today=today)

    assert start == "2026-05-11"
    assert end == "2026-05-17"


def test_resolve_period_dates_last_completed_week_on_monday():
    # On a Monday, last completed week is the immediately preceding Mon–Sun.
    today = datetime.date(2026, 5, 18)

    start, end = resolve_period_dates("上週", today=today)

    assert start == "2026-05-11"
    assert end == "2026-05-17"


def test_resolve_period_dates_last_completed_month():
    today = datetime.date(2026, 5, 21)

    start, end = resolve_period_dates("上月", today=today)

    assert start == "2026-04-01"
    assert end == "2026-04-30"


def test_resolve_period_dates_last_completed_month_january_rolls_year():
    today = datetime.date(2026, 1, 15)

    start, end = resolve_period_dates("上月", today=today)

    assert start == "2025-12-01"
    assert end == "2025-12-31"


def test_resolve_period_dates_current_week_starts_on_monday():
    # Dashboard option: 本週 = this week so far (Mon → today).
    today = datetime.date(2026, 5, 21)

    start, end = resolve_period_dates("本週", today=today)

    assert start == "2026-05-18"
    assert end == "2026-05-21"


def test_resolve_period_dates_current_month_starts_on_first():
    today = datetime.date(2026, 5, 21)

    start, end = resolve_period_dates("本月", today=today)

    assert start == "2026-05-01"
    assert end == "2026-05-21"


def test_resolve_period_dates_last_completed_quarter_mid_year():
    # May 21 → last completed quarter is Q1 (Jan 1 – Mar 31).
    today = datetime.date(2026, 5, 21)

    start, end = resolve_period_dates("上季", today=today)

    assert start == "2026-01-01"
    assert end == "2026-03-31"


def test_resolve_period_dates_last_completed_quarter_january_rolls_year():
    # January → last completed quarter is previous year's Q4.
    today = datetime.date(2026, 1, 15)

    start, end = resolve_period_dates("上季", today=today)

    assert start == "2025-10-01"
    assert end == "2025-12-31"


def test_resolve_period_dates_this_year_ytd():
    today = datetime.date(2026, 5, 21)

    start, end = resolve_period_dates("今年", today=today)

    assert start == "2026-01-01"
    assert end == "2026-05-21"


def test_resolve_period_dates_custom_uses_selected_dates():
    start, end = resolve_period_dates(
        "自訂時間",
        today=datetime.date(2026, 5, 21),
        custom_start=datetime.date(2026, 4, 1),
        custom_end=datetime.date(2026, 4, 30),
    )

    assert start == "2026-04-01"
    assert end == "2026-04-30"
