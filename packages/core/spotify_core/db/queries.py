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


def get_listening_summary(db_path: str) -> dict:
    """Row count, date range, and unique artist/track counts from history.db.

    Args:
        db_path: Path to history.db.

    Returns:
        {
            "total_plays": int,
            "unique_tracks": int,
            "unique_artists": int,
            "earliest_played_at": str | None,
            "latest_played_at": str | None,
        }
    """
    sql = """
        SELECT
            COUNT(*) AS total_plays,
            COUNT(DISTINCT track_id) AS unique_tracks,
            COUNT(DISTINCT artist_name) AS unique_artists,
            MIN(played_at) AS earliest_played_at,
            MAX(played_at) AS latest_played_at
        FROM listening_history
    """
    conn = get_connection(db_path)
    try:
        row = conn.execute(sql).fetchone()
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
