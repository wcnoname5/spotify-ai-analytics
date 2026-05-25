"""Shared period filter helpers for Streamlit views."""
import datetime

import streamlit as st

# Each option dict maps a Chinese radio label to the period_type tag the AI
# report consumes ("weekly" | "monthly" | "custom"). Different views use
# different labels: the dashboard shows the in-progress current week/month,
# while the AI report covers the last completed week/month.
REPORT_PERIOD_OPTION: dict[str, str] = {
    "上週": "weekly",
    "上月": "monthly",
    "自訂時間": "custom",
}

DASHBOARD_PERIOD_OPTION: dict[str, str] = {
    "本週": "weekly",
    "本月": "monthly",
    "自訂時間": "custom",
}


def resolve_period_dates(
    choice: str,
    *,
    today: datetime.date | None = None,
    custom_start: datetime.date | None = None,
    custom_end: datetime.date | None = None,
) -> tuple[str, str]:
    """Resolve a period choice into ISO start/end date strings.

    "本週" / "本月" return the in-progress current period (Mon→today,
    1st→today). "上週" / "上月" return the most recently completed period.
    """
    current_date = today or datetime.date.today()
    if choice == "本週":
        start = current_date - datetime.timedelta(days=current_date.weekday())
        end = current_date
    elif choice == "上週":
        this_week_monday = current_date - datetime.timedelta(days=current_date.weekday())
        end = this_week_monday - datetime.timedelta(days=1)  # last Sunday
        start = end - datetime.timedelta(days=6)              # previous Monday
    elif choice == "本月":
        start = current_date.replace(day=1)
        end = current_date
    elif choice == "上月":
        first_of_this_month = current_date.replace(day=1)
        end = first_of_this_month - datetime.timedelta(days=1)  # last day of previous month
        start = end.replace(day=1)
    else:
        start = custom_start or current_date - datetime.timedelta(days=30)
        end = custom_end or current_date
    return start.isoformat(), end.isoformat()


def render_period_dates(
    key_prefix: str,
    period_option: dict[str, str] = REPORT_PERIOD_OPTION,
) -> tuple[str, str, str]:
    """Render the period filter; return (start_iso, end_iso, period_type).

    `period_option` maps Chinese radio labels (in display order) to the
    period_type tag — pass `DASHBOARD_PERIOD_OPTION` for in-progress periods
    or `REPORT_PERIOD_OPTION` (default) for the last-completed periods used by
    the AI report.
    """
    today = datetime.date.today()
    choice = st.radio(
        "分析區間",
        tuple(period_option.keys()),
        horizontal=True,
        key=f"{key_prefix}_choice",
    )
    custom_start = None
    custom_end = None
    if choice == "自訂時間":
        c1, c2 = st.columns(2)
        custom_start = c1.date_input(
            "開始",
            value=today - datetime.timedelta(days=30),
            key=f"{key_prefix}_custom_start",
        )
        custom_end = c2.date_input("結束", value=today, key=f"{key_prefix}_custom_end")
    start, end = resolve_period_dates(
        choice,
        today=today,
        custom_start=custom_start,
        custom_end=custom_end,
    )
    return start, end, period_option[choice]
