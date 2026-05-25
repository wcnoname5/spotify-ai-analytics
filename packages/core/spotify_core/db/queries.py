"""SQL-backed analytics queries against history.db.

All functions take a db_path and return plain Python structures —
no Polars or in-memory data loading required.
"""
import os
from loguru import logger
from datetime import datetime
from typing import Optional
from .errors import HistoryNotInitializedError
from .migrations import get_connection

_DATE_FMT = "%Y-%m-%d"


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


def _date_window(
    start_date: Optional[str], end_date: Optional[str]
) -> tuple[list[str], list]:
    """Return (where_clauses, params) for an inclusive played_at date range.

    end_date is widened to end-of-day so the boundary day is fully included.
    Either bound may be None; the matching clause is then omitted.
    """
    clauses: list[str] = []
    params: list = []
    if start_date is not None:
        clauses.append("played_at >= ?")
        params.append(start_date)
    if end_date is not None:
        clauses.append("played_at <= ?")
        params.append(end_date + "T23:59:59Z")
    return clauses, params


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
    where_clauses = ["artist_name IS NOT NULL"]
    date_clauses, params = _date_window(start_date, end_date)
    where_clauses += date_clauses

    where_sql = " AND ".join(where_clauses)
    sql = f"""
        SELECT artist_name,
               SUM(ms_played) / 60000 AS total_mins,
               COUNT(*) AS play_count
        FROM listening_history
        WHERE {where_sql}
        GROUP BY artist_name
        ORDER BY total_mins DESC
        LIMIT ?
    """
    params.append(limit)

    conn = get_connection(db_path)
    try:
        rows = conn.execute(sql, params).fetchall()
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
    show_track_id: bool = False,
) -> list[dict]:
    """Top tracks by play count from history.db.

    Args:
        db_path: Path to history.db.
        limit: Number of tracks to return.
        start_date: ISO date string "YYYY-MM-DD" (inclusive, optional).
        end_date: ISO date string "YYYY-MM-DD" (inclusive, optional).
        show_track_id: If True, include track_id (Spotify URI) in each result row.

    Returns:
        List of {"track_name": str, "artist_name": str, "play_count": int, "total_mins": int}
        plus "track_id": str when show_track_id is True.
    """
    _validate_date_range(start_date, end_date)
    _ensure_history_db(db_path)
    where_clauses = ["track_name IS NOT NULL"]
    date_clauses, params = _date_window(start_date, end_date)
    where_clauses += date_clauses

    where_sql = " AND ".join(where_clauses)
    id_col = ", track_id" if show_track_id else ""
    sql = f"""
        SELECT track_name,
               artist_name,
               COUNT(*) AS play_count,
               SUM(ms_played) / 60000 AS total_mins
               {id_col}
        FROM listening_history
        WHERE {where_sql}
        GROUP BY track_id
        ORDER BY play_count DESC, total_mins DESC
        LIMIT ?
    """
    params.append(limit)

    conn = get_connection(db_path)
    try:
        rows = conn.execute(sql, params).fetchall()
        result = [dict(r) for r in rows]
        logger.debug("get_top_tracks: returned {} tracks", len(result))
        return result
    except Exception:
        logger.exception("get_top_tracks failed: db_path={}", db_path)
        raise
    finally:
        conn.close()


_SKIP_THRESHOLD_MS = 30_000

# Day of Week Map
_DOW_MAP = {
    "0": "Sunday", "1": "Monday", "2": "Tuesday", "3": "Wednesday",
    "4": "Thursday", "5": "Friday", "6": "Saturday",
}

# Stacking order for the daily-activity time segments.
_SEGMENT_ORDER = {"0-6": 0, "7-12": 1, "13-18": 2, "19-23": 3}

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
    logger.debug("Inferred timezone offset from conn_country {}: {}", row["conn_country"], offset)
    return offset


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
    where_clauses, date_params = _date_window(start_date, end_date)
    params: list = [_SKIP_THRESHOLD_MS] + date_params

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    sql = f"""
        SELECT
            COUNT(*) AS total_plays,
            COUNT(DISTINCT track_id) AS unique_tracks,
            COUNT(DISTINCT artist_name) AS unique_artists,
            MIN(played_at) AS earliest_played_at,
            MAX(played_at) AS latest_played_at,
            SUM(ms_played) / 60000 AS total_mins_played,
            CAST(AVG(ms_played) / 60000 AS INTEGER) AS avg_mins_per_play,
            SUM(CASE WHEN ms_played < ? THEN 1 ELSE 0 END) * 1.0
                / NULLIF(COUNT(*), 0) AS skip_rate
        FROM listening_history
        {where_sql}
    """
    conn = get_connection(db_path)
    try:
        row = conn.execute(sql, params).fetchone()
        result = dict(row)
        logger.debug("get_listening_summary: total_plays={}", result.get("total_plays"))
        return result
    except Exception:
        logger.exception("get_listening_summary failed: db_path={}", db_path)
        raise
    finally:
        conn.close()


def get_recent_plays(db_path: str, limit: int = 10, show_track_id: bool = False) -> list[dict]:
    """Most recent plays ordered by played_at descending.

    Args:
        db_path: Path to history.db.
        limit: Number of rows to return.
        show_track_id: If True, include track_id (Spotify URI) in each result row.

    Returns:
        List of {"track_name", "artist_name", "album_name", "played_at", "ms_played"}
        plus "track_id": str when show_track_id is True.
    """
    _ensure_history_db(db_path)
    logger.debug("get_recent_plays: limit={}", limit)
    id_col = ", track_id" if show_track_id else ""
    sql = f"""
        SELECT track_name, artist_name, album_name, played_at, ms_played{id_col}
        FROM listening_history
        ORDER BY played_at DESC
        LIMIT ?
    """
    conn = get_connection(db_path)
    try:
        rows = conn.execute(sql, (limit,)).fetchall()
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
    where_clauses, params = _date_window(start_date, end_date)

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    conn = get_connection(db_path)
    try:
        offset = _detect_tz_offset(conn)
        # Build a SQLite datetime modifier string, e.g. "+8 hours" or "-5 hours".
        # Records without conn_country (newer API syncs) are excluded from country
        # detection but still appear in the pattern queries unchanged.
        tz_mod = f"+{offset} hours" if offset >= 0 else f"{offset} hours"
        local_ts = f"datetime(played_at, '{tz_mod}')"

        row = conn.execute(
            f"SELECT CAST(strftime('%H', {local_ts}) AS INTEGER) AS hour, COUNT(*) AS cnt "
            f"FROM listening_history {where_sql} GROUP BY hour ORDER BY cnt DESC LIMIT 1",
            params,
        ).fetchone()
        peak_hour = row["hour"] if row else None

        row = conn.execute(
            f"SELECT strftime('%w', {local_ts}) AS dow, COUNT(*) AS cnt "
            f"FROM listening_history {where_sql} GROUP BY dow ORDER BY cnt DESC LIMIT 1",
            params,
        ).fetchone()
        peak_day_of_week = _DOW_MAP.get(row["dow"]) if row else None

        row = conn.execute(
            f"SELECT date({local_ts}) AS d, COUNT(*) AS cnt "
            f"FROM listening_history {where_sql} GROUP BY d ORDER BY cnt DESC LIMIT 1",
            params,
        ).fetchone()
        most_active_date = row["d"] if row else None

        most_active_date_play_count = None
        most_active_date_total_mins = None
        if most_active_date:
            # Combine the date-equality condition with the existing date-range filter so
            # the detail stats are scoped to the same window used to pick the date.
            detail_clauses = [f"date({local_ts}) = ?"] + where_clauses
            detail_where = "WHERE " + " AND ".join(detail_clauses)
            detail_params = [most_active_date] + params
            row = conn.execute(
                f"SELECT COUNT(*) AS play_count, SUM(ms_played) / 60000 AS total_mins "
                f"FROM listening_history {detail_where}",
                detail_params,
            ).fetchone()
            if row:
                most_active_date_play_count = row["play_count"]
                most_active_date_total_mins = row["total_mins"]

        row = conn.execute(
            f"SELECT COUNT(*) * 1.0 / NULLIF(COUNT(DISTINCT date({local_ts})), 0) AS avg "
            f"FROM listening_history {where_sql}",
            params,
        ).fetchone()
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
        row = conn.execute(
            "SELECT MIN(played_at) AS earliest, MAX(played_at) AS latest FROM listening_history"
        ).fetchone()
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
        List of {label_key: str, "total_mins": int, "play_count": int}, ordered
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
                   SUM(ms_played) / 60000 AS total_mins,
                   COUNT(*) AS play_count
            FROM listening_history
            {where_sql}
            GROUP BY bucket
            ORDER BY bucket
        """
        rows = conn.execute(sql, params).fetchall()
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
    return _grouped_trend(db_path, start_date, end_date, "date({ts})", "date")


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
    return _grouped_trend(
        db_path, start_date, end_date,
        "date({ts}, '-' || ((strftime('%w', {ts}) + 6) % 7) || ' days')",
        "week_label",
    )


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
    return _grouped_trend(
        db_path, start_date, end_date, "strftime('%Y-%m', {ts})", "month_label"
    )


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
        "total_mins": int}, ordered by weekday (Monday..Sunday) then segment.
    """
    _validate_date_range(start_date, end_date)
    _ensure_history_db(db_path)
    logger.debug("get_daily_activity_pattern: start={} end={}", start_date, end_date)
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
                SUM(ms_played) / 60000 AS total_mins
            FROM listening_history
            {where_sql}
            GROUP BY dow, segment
        """
        rows = conn.execute(sql, params).fetchall()
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
