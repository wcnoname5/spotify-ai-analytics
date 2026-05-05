"""SQL-backed analytics queries against history.db.

All functions take a db_path and return plain Python structures —
no Polars or in-memory data loading required.
"""
import logging
from datetime import datetime
from typing import Optional
from .migrations import get_connection

logger = logging.getLogger(__name__)

_DATE_FMT = "%Y-%m-%d"


def _validate_date_range(start_date: Optional[str], end_date: Optional[str]) -> None:
    """Raise ValueError on malformed dates; warn on illogical range."""
    logger.debug("[Helper] _validate_date_range: %s to %s", start_date or "the beginning", end_date or "the end")
    for label, value in (("start_date", start_date), ("end_date", end_date)):
        if value is not None:
            try:
                datetime.strptime(value, _DATE_FMT)
            except ValueError:
                raise ValueError(
                    f"arg {label}={value!r} must be ISO format 'YYYY-MM-DD'"
                )
    if start_date and end_date and start_date > end_date:
        logger.warning("start_date %s is after end_date %s — query will return no rows", start_date, end_date)


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
        List of {"artist_name": str, "total_ms": int, "play_count": int}.
    """
    _validate_date_range(start_date, end_date)
    logger.debug("get_top_artists: limit=%d start=%s end=%s", limit, start_date, end_date)
    where_clauses = ["artist_name IS NOT NULL"]
    params: list = []
    if start_date:
        where_clauses.append("played_at >= ?")
        params.append(start_date)
    if end_date:
        where_clauses.append("played_at <= ?")
        params.append(end_date + "T23:59:59Z")

    where_sql = " AND ".join(where_clauses)
    sql = f"""
        SELECT artist_name,
               SUM(ms_played) AS total_ms,
               COUNT(*) AS play_count
        FROM listening_history
        WHERE {where_sql}
        GROUP BY artist_name
        ORDER BY total_ms DESC
        LIMIT ?
    """
    params.append(limit)

    conn = get_connection(db_path)
    try:
        rows = conn.execute(sql, params).fetchall()
        result = [dict(r) for r in rows]
        logger.info("get_top_artists: returned %d artists", len(result))
        return result
    except Exception:
        logger.exception("get_top_artists failed: db_path=%s", db_path)
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
        List of {"track_name": str, "artist_name": str, "play_count": int, "total_ms": int}
        plus "track_id": str when show_track_id is True.
    """
    _validate_date_range(start_date, end_date)
    logger.debug("get_top_tracks: limit=%d start=%s end=%s", limit, start_date, end_date)
    where_clauses = ["track_name IS NOT NULL"]
    params: list = []
    if start_date:
        where_clauses.append("played_at >= ?")
        params.append(start_date)
    if end_date:
        where_clauses.append("played_at <= ?")
        params.append(end_date + "T23:59:59Z")

    where_sql = " AND ".join(where_clauses)
    id_col = ", track_id" if show_track_id else ""
    sql = f"""
        SELECT track_name,
               artist_name,
               COUNT(*) AS play_count,
               SUM(ms_played) AS total_ms
               {id_col}
        FROM listening_history
        WHERE {where_sql}
        GROUP BY track_id
        ORDER BY play_count DESC
        LIMIT ?
    """
    params.append(limit)

    conn = get_connection(db_path)
    try:
        rows = conn.execute(sql, params).fetchall()
        result = [dict(r) for r in rows]
        logger.info("get_top_tracks: returned %d tracks", len(result))
        return result
    except Exception:
        logger.exception("get_top_tracks failed: db_path=%s", db_path)
        raise
    finally:
        conn.close()


_SKIP_THRESHOLD_MS = 30_000

_DOW_MAP = {
    "0": "Sunday", "1": "Monday", "2": "Tuesday", "3": "Wednesday",
    "4": "Thursday", "5": "Friday", "6": "Saturday",
}

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
    logger.debug("[Helper] _detect_tz_offset: detecting timezone offset from conn_country")
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
    logger.debug("Inferred timezone offset from conn_country %s: %s", row["conn_country"], offset)
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
            "total_ms_played": int | None,
            "avg_ms_per_play": float | None,
            "skip_rate": float | None,  -- fraction of plays < 30 s
        }
    """
    _validate_date_range(start_date, end_date)
    logger.debug("get_listening_summary: start=%s end=%s", start_date, end_date)
    where_clauses = []
    params: list = [_SKIP_THRESHOLD_MS]
    if start_date:
        where_clauses.append("played_at >= ?")
        params.append(start_date)
    if end_date:
        where_clauses.append("played_at <= ?")
        params.append(end_date + "T23:59:59Z")

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    sql = f"""
        SELECT
            COUNT(*) AS total_plays,
            COUNT(DISTINCT track_id) AS unique_tracks,
            COUNT(DISTINCT artist_name) AS unique_artists,
            MIN(played_at) AS earliest_played_at,
            MAX(played_at) AS latest_played_at,
            SUM(ms_played) AS total_ms_played,
            AVG(ms_played) AS avg_ms_per_play,
            SUM(CASE WHEN ms_played < ? THEN 1 ELSE 0 END) * 1.0
                / NULLIF(COUNT(*), 0) AS skip_rate
        FROM listening_history
        {where_sql}
    """
    conn = get_connection(db_path)
    try:
        row = conn.execute(sql, params).fetchone()
        result = dict(row)
        logger.info("get_listening_summary: total_plays=%s", result.get("total_plays"))
        return result
    except Exception:
        logger.exception("get_listening_summary failed: db_path=%s", db_path)
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
    logger.debug("get_recent_plays: limit=%d", limit)
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
        logger.info("get_recent_plays: returned %d rows", len(result))
        return result
    except Exception:
        logger.exception("get_recent_plays failed: db_path=%s", db_path)
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
            "most_active_date": str | None,           -- YYYY-MM-DD (local date) with most plays
            "most_active_date_play_count": int | None,-- play count on most_active_date
            "most_active_date_total_ms": int | None,  -- total ms played on most_active_date
            "avg_plays_per_day": float | None,        -- plays / distinct local calendar days
        }
    """
    _validate_date_range(start_date, end_date)
    logger.debug("get_listening_patterns: start=%s end=%s", start_date, end_date)
    where_clauses = []
    params: list = []
    if start_date:
        where_clauses.append("played_at >= ?")
        params.append(start_date)
    if end_date:
        where_clauses.append("played_at <= ?")
        params.append(end_date + "T23:59:59Z")

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
        most_active_date_total_ms = None
        if most_active_date:
            # Combine the date-equality condition with the existing date-range filter so
            # the detail stats are scoped to the same window used to pick the date.
            detail_clauses = [f"date({local_ts}) = ?"] + where_clauses
            detail_where = "WHERE " + " AND ".join(detail_clauses)
            detail_params = [most_active_date] + params
            row = conn.execute(
                f"SELECT COUNT(*) AS play_count, SUM(ms_played) AS total_ms "
                f"FROM listening_history {detail_where}",
                detail_params,
            ).fetchone()
            if row:
                most_active_date_play_count = row["play_count"]
                most_active_date_total_ms = row["total_ms"]

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
            "most_active_date_total_ms": most_active_date_total_ms,
            "avg_plays_per_day": avg_plays_per_day,
        }
        logger.info("get_listening_patterns: peak_hour=%s peak_day=%s", peak_hour, peak_day_of_week)
        return result
    except Exception:
        logger.exception("get_listening_patterns failed: db_path=%s", db_path)
        raise
    finally:
        conn.close()


def is_history_empty(db_path: str) -> bool:
    """Return True if the DB file is missing, has no table, or has zero rows."""
    import os
    import sqlite3 as _sqlite3
    logger.debug("is_history_empty: db_path=%s", db_path)
    if not os.path.exists(db_path):
        logger.info("is_history_empty: DB file not found at %s", db_path)
        return True
    try:
        conn = get_connection(db_path)
        try:
            row = conn.execute("SELECT COUNT(*) FROM listening_history").fetchone()
            empty = row[0] == 0
            logger.info("is_history_empty: %s (row_count=%d)", empty, row[0])
            return empty
        except _sqlite3.OperationalError:
            logger.warning("is_history_empty: listening_history table missing in %s", db_path)
            return True
        finally:
            conn.close()
    except Exception:
        logger.exception("is_history_empty: failed to open db_path=%s", db_path)
        return True

def get_data_range(db_path: str) -> Optional[tuple[str, str]]:
    """Return the earliest and latest played_at timestamps in the DB, or None if empty."""
    import os
    import sqlite3 as _sqlite3
    logger.debug("get_data_range: db_path=%s", db_path)
    try:
        conn = get_connection(db_path)
        try:
            row = conn.execute("SELECT MIN(played_at) AS earliest, MAX(played_at) AS latest FROM listening_history").fetchone()
            earliest = row["earliest"] if row else None
            latest = row["latest"] if row else None
            logger.info("get_data_range: earliest=%s, latest=%s", earliest, latest)
            return (earliest, latest)
        except _sqlite3.OperationalError:
            logger.warning("get_data_range: listening_history table missing in %s", db_path)
            return None
        finally:
            conn.close()
    except FileNotFoundError as e:
        logger.exception("get_data_range: DB file not found at %s", db_path)
        return None
    except Exception:
        logger.exception("get_data_range: failed to open db_path=%s", db_path)
        return None