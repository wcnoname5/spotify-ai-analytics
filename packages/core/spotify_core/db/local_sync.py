"""Pull-only incremental sync: refresh the local SQLite cache from D1.

D1 (via the Worker) is the single source of truth. This module never writes
to D1 — it only reads new rows through ``WorkerClient.get_tracks_since`` and
upserts them into the local ``listening_history`` cache, then advances a
local-only cursor (``meta.last_sync_at_ms``) so the next run only asks for
what's new.
"""
from pathlib import Path
from typing import Union

from loguru import logger

from .migrations import get_connection, init_history_db, init_meta_table
from .worker_client import WorkerClient

_COLUMNS = (
    "id", "track_id", "track_name", "artist_name", "album_name",
    "played_at", "ms_played", "source",
    "platform", "conn_country", "reason_start", "reason_end",
    "shuffle", "skipped",
)


def _get_last_sync_at_ms(conn) -> int:
    row = conn.execute(
        "SELECT value FROM meta WHERE key = 'last_sync_at_ms'"
    ).fetchone()
    if row is None or row["value"] is None:
        return 0
    return int(row["value"])


def _set_last_sync_at_ms(conn, ms: int) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES ('last_sync_at_ms', ?)",
        (str(ms),),
    )


def run_local_sync(db_path: Union[str, Path], worker: WorkerClient) -> dict:
    """Pull new rows from D1 (via the Worker) into the local SQLite cache.

    Args:
        db_path: Path to the local history SQLite DB (the pull-only cache).
        worker: An authenticated WorkerClient.

    Returns:
        dict with keys: fetched, inserted, skipped_duplicated, cursor_ms.
    """
    init_history_db(db_path)
    init_meta_table(db_path)

    conn = get_connection(db_path)
    try:
        with conn:
            last_sync_at_ms = _get_last_sync_at_ms(conn)
            # Read the cursor BEFORE fetching tracks: if new rows land in D1
            # between these two calls, this run simply misses them (they'll
            # be picked up next time) rather than permanently skipping rows
            # that arrived between get_tracks_since and get_cursor.
            cursor_ms = worker.get_cursor()
            rows = worker.get_tracks_since(last_sync_at_ms)

            inserted = 0
            for row in rows:
                cur = conn.execute(
                    "INSERT OR IGNORE INTO listening_history "
                    "(id, track_id, track_name, artist_name, album_name, "
                    " played_at, ms_played, source, "
                    " platform, conn_country, reason_start, reason_end, shuffle, skipped) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    tuple(row.get(col) for col in _COLUMNS),
                )
                if cur.rowcount > 0:
                    inserted += 1

            _set_last_sync_at_ms(conn, cursor_ms)
    finally:
        conn.close()

    result = {
        "fetched": len(rows),
        "inserted": inserted,
        "skipped_duplicated": len(rows) - inserted,
        "cursor_ms": cursor_ms,
    }
    logger.info("Local sync: {}", result)
    return result
