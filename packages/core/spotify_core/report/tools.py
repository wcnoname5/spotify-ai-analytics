"""LangChain @tool wrappers around db/queries.py for the report drafter.

make_report_tools(db_path) binds db_path via closure; the LLM only supplies the
start_date / end_date arguments. Each tool's docstring is its LLM-facing
description. The three trend granularities are three separate tools — the LLM
chooses which to call, guided by their docstrings.
"""
from loguru import logger
from langchain_core.tools import BaseTool, tool

from ..db import queries


def make_report_tools(db_path: str) -> list[BaseTool]:
    """Build the drafter's data tools, each bound to db_path via closure."""
    @tool
    def get_listening_summary(start_date: str, end_date: str) -> dict:
        """Overall listening stats for the date range: total plays, listening
        time, unique tracks/artists, skip rate. Dates are ISO 'YYYY-MM-DD'."""
        return queries.get_listening_summary(
            db_path, start_date=start_date, end_date=end_date
        )
    @tool
    def get_top_artists(
        start_date: str,
        end_date: str,
        limit: int = 10,
    ) -> list[dict]:
        """The most-listened artists for the date range, ranked by listening
        time. Dates are ISO 'YYYY-MM-DD'. `limit` controls how many artists
        to return (default 10)."""
        return queries.get_top_artists(
            db_path, limit=limit, start_date=start_date, end_date=end_date
        )

    @tool
    def get_top_tracks(
        start_date: str,
        end_date: str,
        limit: int = 10,
    ) -> list[dict]:
        """The most-played tracks for the date range, ranked by play count.
        Dates are ISO 'YYYY-MM-DD'. `limit` controls how many tracks to
        return (default 10)."""
        return queries.get_top_tracks(
            db_path, limit=limit, start_date=start_date, end_date=end_date
        )

    @tool
    def get_daily_activity_pattern(start_date: str, end_date: str) -> list[dict]:
        """Listening volume per weekday and per time-of-day segment (00:00-06:59,
        07:00-12:59, 13:00-18:59, 19:00-23:59) for the date range. Dates are ISO 'YYYY-MM-DD'."""
        return queries.get_daily_activity_pattern(
            db_path, start_date=start_date, end_date=end_date
        )

    @tool
    def get_daily_trend(start_date: str, end_date: str) -> list[dict]:
        """Per-calendar-day listening totals for the date range. Best for short
        ranges of up to about two weeks. Dates are ISO 'YYYY-MM-DD'."""
        return queries.get_daily_trend(
            db_path, start_date=start_date, end_date=end_date
        )

    @tool
    def get_weekly_trend(start_date: str, end_date: str) -> list[dict]:
        """Per-week listening totals for the date range. Best for medium ranges
        of roughly one to three months. Dates are ISO 'YYYY-MM-DD'."""
        return queries.get_weekly_trend(
            db_path, start_date=start_date, end_date=end_date
        )

    @tool
    def get_monthly_trend(start_date: str, end_date: str) -> list[dict]:
        """Per-month listening totals for the date range. Best for long ranges
        of several months or more. Dates are ISO 'YYYY-MM-DD'."""
        return queries.get_monthly_trend(
            db_path, start_date=start_date, end_date=end_date
        )

    tools: list[BaseTool] = [
        get_listening_summary,
        get_top_artists,
        get_top_tracks,
        get_daily_activity_pattern,
        get_daily_trend,
        get_weekly_trend,
        get_monthly_trend,
    ]
    logger.info("make_report_tools: built {} tools", len(tools))
    return tools
