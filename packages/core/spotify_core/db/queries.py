"""SQL-backed analytics queries against history.db.

All functions take a db_path and return plain Python structures.

Query bodies live in packages/core/spotify_core/db/sql/*.sql (shared with the
Tauri dashboard's TS data layer) — this module only loads, binds params, and
shapes results.
"""
import os
from importlib.resources import files
from loguru import logger
from datetime import datetime
from typing import Optional
from .errors import HistoryNotInitializedError
from .migrations import get_connection

_DATE_FMT = "%Y-%m-%d"


def _sql(name: str) -> str:
    """Load a query body from db/sql/<name>.sql."""
    return files("spotify_core.db.sql").joinpath(f"{name}.sql").read_text()


def _ensure_history_db(db_path: str) -> None:
    """Raise HistoryNotInitializedError if the file or listening_history table is missing."""
    if not os.path.exists(db_path):
        raise HistoryNotInitializedError(
            f"History DB not found at {db_path}. Import or sync history in the app first."
        )
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='listening_history'"
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise HistoryNotInitializedError(
            f"listening_history table missing in {db_path}. Import or sync history in the app first."
        )


def _validate_date_range(start_date: Optional[str], end_date: Optional[str]) -> None:
    """Raise ValueError on malformed dates; warn on illogical range."""
    for label, value in (("start_date", start_date), ("end_date", end_date)):
        if value is not None:
            try:
                datetime.strptime(value, _DATE_FMT)
            except ValueError:
                raise ValueError(
                    f"arg {label}={value!r} must be ISO format 'YYYY-MM-DD'"
                )
    if start_date and end_date and start_date > end_date:
        logger.warning("start_date {} is after end_date {} - query will return no rows", start_date, end_date)


def _widen_end(end_date: Optional[str]) -> Optional[str]:
    """Widen an inclusive end_date to end-of-day so the boundary day is fully included.

    Returns None unchanged (no end bound).
    """
    if end_date is None:
        return None
    return end_date + "T23:59:59Z"


def get_top_artists(
    db_path: str,
    limit: int = 10,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> list[dict]:
    """Top artists by total listening time from history.db.

    Args:
        db_path: Path to history.db.
        limit: Number of artists to return.
        start_date: ISO date string "YYYY-MM-DD" (inclusive, optional).
        end_date: ISO date string "YYYY-MM-DD" (inclusive, optional).

    Returns:
        List of {"artist_name": str, "total_mins": int, "play_count": int}.
    """
    _validate_date_range(start_date, end_date)
    _ensure_history_db(db_path)
    end_widened = _widen_end(end_date)

    conn = get_connection(db_path)
    try:
        rows = conn.execute(_sql("top_artists"), (start_date, end_widened, limit)).fetchall()
        result = [dict(r) for r in rows]
        logger.debug("get_top_artists: returned {} artists", len(result))
        return result
    except Exception:
        logger.exception("get_top_artists failed: db_path={}", db_path)
        raise
    finally:
        conn.close()


def get_top_tracks(
    db_path: str,
    limit: int = 10,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> list[dict]:
    """Top tracks by play count from history.db.

    Args:
        db_path: Path to history.db.
        limit: Number of tracks to return.
        start_date: ISO date string "YYYY-MM-DD" (inclusive, optional).
        end_date: ISO date string "YYYY-MM-DD" (inclusive, optional).

    Returns:
        List of {"track_id": str, "track_name": str, "artist_name": str,
        "play_count": int, "total_mins": int}.
    """
    _validate_date_range(start_date, end_date)
    _ensure_history_db(db_path)
    end_widened = _widen_end(end_date)

    conn = get_connection(db_path)
    try:
        rows = conn.execute(_sql("top_tracks"), (start_date, end_widened, limit)).fetchall()
        result = [dict(r) for r in rows]
        logger.debug("get_top_tracks: returned {} tracks", len(result))
        return result
    except Exception:
        logger.exception("get_top_tracks failed: db_path={}", db_path)
        raise
    finally:
        conn.close()


_DOW_MAP = {
    "0": "Sunday", "1": "Monday", "2": "Tuesday", "3": "Wednesday",
    "4": "Thursday", "5": "Friday", "6": "Saturday",
}

# Stacking order for the daily-activity time segments.
_SEGMENT_ORDER = {"00:00-06:59": 0, "07:00-12:59": 1, "13:00-18:59": 2, "19:00-23:59": 3}


def _tz_modifier() -> str:
    """SQLite datetime modifier for this machine's UTC offset, e.g. '+8 hours'.

    Same rule as `tzModifier()` in apps/tauri/src/lib/queries.ts, so the report
    and the dashboard bucket plays into the same local days and hours.
    """
    offset = datetime.now().astimezone().utcoffset().total_seconds() / 3600
    return f"{'+' if offset >= 0 else ''}{offset:g} hours"


def get_listening_summary(
    db_path: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> dict:
    """Row count, date range, unique counts, and volume stats from history.db.

    Args:
        db_path: Path to history.db.
        start_date: ISO date string "YYYY-MM-DD" (inclusive, optional).
        end_date: ISO date string "YYYY-MM-DD" (inclusive, optional).

    Returns:
        {
            "total_plays": int,
            "unique_tracks": int,
            "unique_artists": int,
            "earliest_played_at": str | None,
            "latest_played_at": str | None,
            "total_mins_played": int | None,
            "avg_mins_per_play": int | None,
            "skip_rate": float | None,  -- fraction of plays < 30 s
        }
    """
    _validate_date_range(start_date, end_date)
    _ensure_history_db(db_path)
    end_widened = _widen_end(end_date)

    conn = get_connection(db_path)
    try:
        row = conn.execute(_sql("listening_summary"), (start_date, end_widened)).fetchone()
        result = dict(row)
        logger.debug("get_listening_summary: total_plays={}", result.get("total_plays"))
        return result
    except Exception:
        logger.exception("get_listening_summary failed: db_path={}", db_path)
        raise
    finally:
        conn.close()


def _grouped_trend(
    db_path: str,
    start_date: Optional[str],
    end_date: Optional[str],
    sql_name: str,
    label_key: str,
) -> list[dict]:
    """Sum ms_played and count plays grouped by a bucket expression on local time.

    Args:
        db_path: Path to history.db.
        start_date: ISO date string "YYYY-MM-DD" (inclusive, optional).
        end_date: ISO date string "YYYY-MM-DD" (inclusive, optional).
        sql_name: Name of the .sql file (in db/sql/) whose bucket column is
            aliased "bucket".
        label_key: Dict key under which the bucket label is returned.

    Returns:
        List of {label_key: str, "total_mins": int, "play_count": int}, ordered
        by bucket ascending.
    """
    _validate_date_range(start_date, end_date)
    _ensure_history_db(db_path)
    end_widened = _widen_end(end_date)

    conn = get_connection(db_path)
    try:
        rows = conn.execute(_sql(sql_name), (start_date, end_widened, _tz_modifier())).fetchall()
        return [
            {label_key: r["bucket"], "total_mins": r["total_mins"] or 0,
             "play_count": r["play_count"]}
            for r in rows
        ]
    except Exception:
        logger.exception("_grouped_trend failed: db_path={} key={}", db_path, label_key)
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
        List of {"date": "YYYY-MM-DD", "total_mins": int, "play_count": int},
        ordered by date ascending.
    """
    return _grouped_trend(db_path, start_date, end_date, "trend_daily", "date")


def get_weekly_trend(
    db_path: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> list[dict]:
    """Per-week listening totals from history.db.

    Weeks are Monday-based. Labels are the ISO date of the week's Monday.

    Returns:
        List of {"week_label": "YYYY-MM-DD", "total_mins": int, "play_count": int},
        ordered by week ascending.
    """
    return _grouped_trend(db_path, start_date, end_date, "trend_weekly", "week_label")


def get_monthly_trend(
    db_path: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> list[dict]:
    """Per-month listening totals from history.db.

    Returns:
        List of {"month_label": "YYYY-MM", "total_mins": int, "play_count": int},
        ordered by month ascending.
    """
    return _grouped_trend(db_path, start_date, end_date, "trend_monthly", "month_label")


def get_daily_activity_pattern(
    db_path: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> list[dict]:
    """Per-weekday, per-time-segment listening volume from history.db.

    Timestamps are shifted to this machine's local time before grouping. Time
    segments are local hour-of-day ranges 00:00-06:59, 07:00-12:59,
    13:00-18:59, 19:00-23:59.

    Args:
        db_path: Path to history.db.
        start_date: ISO date string "YYYY-MM-DD" (inclusive, optional).
        end_date: ISO date string "YYYY-MM-DD" (inclusive, optional).

    Returns:
        List of {"weekday": str, "weekday_idx": int, "segment": str,
        "total_mins": int}, ordered by weekday (Monday..Sunday) then segment.
    """
    _validate_date_range(start_date, end_date)
    _ensure_history_db(db_path)
    logger.debug("get_daily_activity_pattern: start={} end={}", start_date, end_date)
    end_widened = _widen_end(end_date)

    conn = get_connection(db_path)
    try:
        rows = conn.execute(_sql("activity_pattern"), (start_date, end_widened, _tz_modifier())).fetchall()
        result = []
        for r in rows:
            dow = r["dow"]  # '0'..'6', 0 = Sunday
            result.append({
                "weekday": _DOW_MAP[dow],
                "weekday_idx": (int(dow) + 6) % 7,  # 0 = Mon .. 6 = Sun
                "segment": r["segment"],
                "total_mins": r["total_mins"] or 0,
            })
        result.sort(key=lambda d: (d["weekday_idx"], _SEGMENT_ORDER[d["segment"]]))
        logger.debug("get_daily_activity_pattern: {} (weekday, segment) rows", len(result))
        return result
    except Exception:
        logger.exception("get_daily_activity_pattern failed: db_path={}", db_path)
        raise
    finally:
        conn.close()
