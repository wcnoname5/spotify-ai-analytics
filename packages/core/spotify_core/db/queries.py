"""SQL-backed analytics queries against history.db.

All functions take a db_path and return plain Python structures —
no Polars or in-memory data loading required.

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
            f"History DB not found at {db_path}. Run import_history_from_json or sync_history first."
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
            f"listening_history table missing in {db_path}. Run import_history_from_json or sync_history first."
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


# Day of Week Map
_DOW_MAP = {
    "0": "Sunday", "1": "Monday", "2": "Tuesday", "3": "Wednesday",
    "4": "Thursday", "5": "Friday", "6": "Saturday",
}

# Stacking order for the daily-activity time segments.
_SEGMENT_ORDER = {"00:00-06:59": 0, "07:00-12:59": 1, "13:00-18:59": 2, "19:00-23:59": 3}

# Country code → UTC offset in hours. Fractional-offset countries (e.g. IN +5:30) are
# approximated to the nearest integer. Multi-timezone countries (US, CA, RU, AU) use
# their most-populated timezone as a rough default.
_COUNTRY_UTC_OFFSET: dict[str, int] = {
    # Asia-Pacific
    "TW": 8, "CN": 8, "HK": 8, "SG": 8, "MY": 8, "PH": 8, "BN": 8,
    "JP": 9, "KR": 9,
    "TH": 7, "VN": 7, "ID": 7, "CX": 7,
    "IN": 5,  # IST is +5:30; approximated
    "PK": 5, "UZ": 5,
    "NP": 6,  # +5:45 approximated
    "AU": 10, "NZ": 12,
    # Middle East
    "AE": 4, "OM": 4, "MU": 4,
    "SA": 3, "IQ": 3, "KW": 3, "QA": 3, "BH": 3, "YE": 3, "JO": 3, "KE": 3,
    "IR": 4,  # +3:30 approximated
    "TR": 3,
    # Europe (standard offsets; DST not accounted for)
    "GB": 0, "IE": 0, "PT": 0, "IS": 0,
    "FR": 1, "DE": 1, "IT": 1, "ES": 1, "NL": 1, "BE": 1, "LU": 1,
    "AT": 1, "CH": 1, "SE": 1, "NO": 1, "DK": 1, "PL": 1, "CZ": 1,
    "SK": 1, "HU": 1, "HR": 1, "SI": 1, "RS": 1, "BA": 1, "ME": 1, "AL": 1,
    "FI": 2, "EE": 2, "LV": 2, "LT": 2, "GR": 2, "RO": 2, "BG": 2, "UA": 2,
    "CY": 2, "IL": 2, "EG": 2, "ZA": 2,
    "RU": 3,  # Moscow time (Russia spans many zones)
    # Americas
    "US": -5, "CA": -5,  # Eastern; both span multiple zones
    "MX": -6,
    "CO": -5, "PE": -5, "EC": -5,
    "VE": -4, "BO": -4, "PY": -4, "CL": -3,
    "BR": -3, "AR": -3, "UY": -3,
    # Africa
    "NG": 1, "MA": 1, "GH": 0, "ET": 3,
}


def _detect_tz_offset(conn) -> int:
    """Return the UTC offset (hours) inferred from the most common conn_country.

    Looks across all records with a non-NULL conn_country. Returns 0 (UTC) when
    no country data is present or the country is not in the lookup table.
    """
    row = conn.execute(
        "SELECT conn_country, COUNT(*) AS cnt "
        "FROM listening_history WHERE conn_country IS NOT NULL "
        "GROUP BY conn_country ORDER BY cnt DESC LIMIT 1"
    ).fetchone()
    if not row:
        # if no records have a conn_country, default to UTC with no offset
        logger.debug("No conn_country data found; defaulting to UTC with offset 0")
        return 0
    offset = _COUNTRY_UTC_OFFSET.get(row["conn_country"], 0)
    return offset


def _tz_modifier(offset: int) -> str:
    """Return a SQLite datetime modifier string, e.g. '+8 hours' or '-5 hours'."""
    return f"+{offset} hours" if offset >= 0 else f"{offset} hours"


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


def get_recent_plays(db_path: str, limit: int = 10) -> list[dict]:
    """Most recent plays ordered by played_at descending.

    Args:
        db_path: Path to history.db.
        limit: Number of rows to return.

    Returns:
        List of {"track_name", "artist_name", "album_name", "played_at",
        "ms_played", "track_id"}.
    """
    _ensure_history_db(db_path)

    conn = get_connection(db_path)
    try:
        rows = conn.execute(_sql("recent_plays"), (None, None, limit)).fetchall()
        result = [dict(r) for r in rows]
        logger.debug("get_recent_plays: returned {} rows", len(result))
        return result
    except Exception:
        logger.exception("get_recent_plays failed: db_path={}", db_path)
        raise
    finally:
        conn.close()


def get_listening_patterns(
    db_path: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> dict:
    """Temporal listening patterns from history.db.

    Timestamps are shifted to local time before grouping, using the UTC offset
    inferred from the most common conn_country across all records. Records that
    lack conn_country (e.g. recent API syncs) are still included in the pattern
    queries but do not influence timezone detection.

    Args:
        db_path: Path to history.db.
        start_date: ISO date string "YYYY-MM-DD" (inclusive, optional).
        end_date: ISO date string "YYYY-MM-DD" (inclusive, optional).

    Returns:
        {
            "peak_hour": int | None,                  -- local hour-of-day 0-23 with most plays
            "peak_day_of_week": str | None,           -- e.g. "Thursday" (local time)
            "most_active_date": str | None,              -- YYYY-MM-DD (local date) with most plays
            "most_active_date_play_count": int | None,   -- play count on most_active_date
            "most_active_date_total_mins": int | None,   -- total minutes played on most_active_date
            "avg_plays_per_day": float | None,           -- plays / distinct local calendar days
        }
    """
    _validate_date_range(start_date, end_date)
    _ensure_history_db(db_path)
    logger.debug("get_listening_patterns: start={} end={}", start_date, end_date)
    end_widened = _widen_end(end_date)

    conn = get_connection(db_path)
    try:
        offset = _detect_tz_offset(conn)
        tz_mod = _tz_modifier(offset)
        params = (start_date, end_widened, tz_mod)

        row = conn.execute(_sql("patterns_peak_hour"), params).fetchone()
        peak_hour = row["hour"] if row else None

        row = conn.execute(_sql("patterns_peak_dow"), params).fetchone()
        peak_day_of_week = _DOW_MAP.get(row["dow"]) if row else None

        row = conn.execute(_sql("patterns_top_date"), params).fetchone()
        most_active_date = row["d"] if row else None

        most_active_date_play_count = None
        most_active_date_total_mins = None
        if most_active_date:
            detail_params = (start_date, end_widened, tz_mod, most_active_date)
            row = conn.execute(_sql("patterns_date_detail"), detail_params).fetchone()
            if row:
                most_active_date_play_count = row["play_count"]
                most_active_date_total_mins = row["total_mins"]

        row = conn.execute(_sql("patterns_avg_per_day"), params).fetchone()
        avg_plays_per_day = row["avg"] if row else None

        result = {
            "peak_hour": peak_hour,
            "peak_day_of_week": peak_day_of_week,
            "most_active_date": most_active_date,
            "most_active_date_play_count": most_active_date_play_count,
            "most_active_date_total_mins": most_active_date_total_mins,
            "avg_plays_per_day": avg_plays_per_day,
        }
        logger.debug("get_listening_patterns: peak_hour={} peak_day={}", peak_hour, peak_day_of_week)
        return result
    except Exception:
        logger.exception("get_listening_patterns failed: db_path={}", db_path)
        raise
    finally:
        conn.close()


def is_history_empty(db_path: str) -> bool:
    """Return True if the DB file is missing, has no listening_history table, or has zero rows."""
    try:
        _ensure_history_db(db_path)
    except HistoryNotInitializedError as e:
        logger.warning("is_history_empty: {}", e)
        return True

    conn = get_connection(db_path)
    try:
        row = conn.execute("SELECT COUNT(*) FROM listening_history").fetchone()
        empty = row[0] == 0
        return empty
    finally:
        conn.close()


def get_data_range(db_path: str) -> Optional[tuple[str, str]]:
    """Return the earliest and latest played_at timestamps, or None if the DB is uninitialized."""
    logger.debug("get_data_range: db_path={}", db_path)
    try:
        _ensure_history_db(db_path)
    except HistoryNotInitializedError as e:
        logger.error("get_data_range: {}", e)
        return None

    conn = get_connection(db_path)
    try:
        row = conn.execute(_sql("data_range")).fetchone()
        earliest = row["earliest"] if row else None
        latest = row["latest"] if row else None
        logger.debug("get_data_range: earliest={}, latest={}", earliest, latest)
        return (earliest, latest)
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
        offset = _detect_tz_offset(conn)
        tz_mod = _tz_modifier(offset)
        rows = conn.execute(_sql(sql_name), (start_date, end_widened, tz_mod)).fetchall()
        result = [
            {label_key: r["bucket"], "total_mins": r["total_mins"] or 0,
             "play_count": r["play_count"]}
            for r in rows
        ]
        return result
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

    Timestamps are shifted to local time (offset inferred from conn_country)
    before grouping. Time segments are local hour-of-day ranges 00:00-06:59,
    07:00-12:59, 13:00-18:59, 19:00-23:59.

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
        offset = _detect_tz_offset(conn)
        tz_mod = _tz_modifier(offset)
        rows = conn.execute(_sql("activity_pattern"), (start_date, end_widened, tz_mod)).fetchall()
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
