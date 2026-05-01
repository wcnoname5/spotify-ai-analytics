"""SQL-backed analytics queries against history.db.

All functions take a db_path and return plain Python structures —
no Polars or in-memory data loading required.
"""
import logging
from typing import Optional
from .migrations import get_connection

logger = logging.getLogger(__name__)


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
        return [dict(r) for r in rows]
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
        return [dict(r) for r in rows]
    finally:
        conn.close()


_SKIP_THRESHOLD_MS = 30_000

_DOW_MAP = {
    "0": "Sunday", "1": "Monday", "2": "Tuesday", "3": "Wednesday",
    "4": "Thursday", "5": "Friday", "6": "Saturday",
}


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
        return dict(row)
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
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_listening_patterns(
    db_path: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> dict:
    """Temporal listening patterns from history.db.

    Args:
        db_path: Path to history.db.
        start_date: ISO date string "YYYY-MM-DD" (inclusive, optional).
        end_date: ISO date string "YYYY-MM-DD" (inclusive, optional).

    Returns:
        {
            "peak_hour": int | None,           -- hour-of-day 0-23 with most plays
            "peak_day_of_week": str | None,    -- e.g. "Thursday"
            "most_active_date": str | None,    -- YYYY-MM-DD with most plays
            "avg_plays_per_day": float | None, -- plays / distinct calendar days
        }
    """
    # TODO: you should consider timezone effects here.
    
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
        row = conn.execute(
            f"SELECT CAST(strftime('%H', played_at) AS INTEGER) AS hour, COUNT(*) AS cnt "
            f"FROM listening_history {where_sql} GROUP BY hour ORDER BY cnt DESC LIMIT 1",
            params,
        ).fetchone()
        peak_hour = row["hour"] if row else None

        row = conn.execute(
            f"SELECT strftime('%w', played_at) AS dow, COUNT(*) AS cnt "
            f"FROM listening_history {where_sql} GROUP BY dow ORDER BY cnt DESC LIMIT 1",
            params,
        ).fetchone()
        peak_day_of_week = _DOW_MAP.get(row["dow"]) if row else None

        row = conn.execute(
            f"SELECT date(played_at) AS d, COUNT(*) AS cnt "
            f"FROM listening_history {where_sql} GROUP BY d ORDER BY cnt DESC LIMIT 1",
            params,
        ).fetchone()
        most_active_date = row["d"] if row else None

        row = conn.execute(
            f"SELECT COUNT(*) * 1.0 / NULLIF(COUNT(DISTINCT date(played_at)), 0) AS avg "
            f"FROM listening_history {where_sql}",
            params,
        ).fetchone()
        avg_plays_per_day = row["avg"] if row else None

        return {
            "peak_hour": peak_hour,
            "peak_day_of_week": peak_day_of_week,
            "most_active_date": most_active_date,
            "avg_plays_per_day": avg_plays_per_day,
        }
    finally:
        conn.close()


def is_history_empty(db_path: str) -> bool:
    """Return True if the DB file is missing, has no table, or has zero rows."""
    import os
    import sqlite3 as _sqlite3
    if not os.path.exists(db_path):
        return True
    try:
        conn = get_connection(db_path)
        try:
            row = conn.execute("SELECT COUNT(*) FROM listening_history").fetchone()
            return row[0] == 0
        except _sqlite3.OperationalError:
            # Table doesn't exist yet
            return True
        finally:
            conn.close()
    except Exception:
        return True
