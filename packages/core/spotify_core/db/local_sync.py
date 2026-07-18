"""Pull-only incremental sync: refresh the local SQLite cache from D1.

D1 (via the Worker) is the single source of truth. This module never writes
to D1 — it only reads new rows through ``WorkerClient.get_tracks_since`` and
upserts them into the local ``listening_history`` cache. The sync cursor is
simply ``MAX(played_at)`` of the cache itself, so there is no separate
bookkeeping table and nothing that can drift out of step with the data.
"""
from importlib.resources import files
from pathlib import Path
from typing import Union

from loguru import logger

from .migrations import get_connection, init_history_db
from .worker_client import WorkerClient

_EPOCH_ISO = "1970-01-01T00:00:00Z"


def _sql(name: str) -> str:
    """Load a query body from db/sql/<name>.sql."""
    return files("spotify_core.db.sql").joinpath(f"{name}.sql").read_text()

_COLUMNS = (
    "id", "track_id", "track_name", "artist_name", "album_name",
    "played_at", "ms_played", "source",
    "platform", "conn_country", "reason_start", "reason_end",
    "shuffle", "skipped",
)


def run_local_sync(db_path: Union[str, Path], worker: WorkerClient) -> dict:
    """Pull new rows from D1 (via the Worker) into the local SQLite cache.

    Args:
        db_path: Path to the local history SQLite DB (the pull-only cache).
        worker: An authenticated WorkerClient.

    Returns:
        dict with keys: fetched, inserted, skipped_duplicated, cursor.
    """
    init_history_db(db_path)

    conn = get_connection(db_path)
    try:
        with conn:
            cursor = conn.execute(_sql("max_played_at")).fetchone()["c"] or _EPOCH_ISO
            rows = worker.get_tracks_since(cursor)

            insert_sql = _sql("insert_track")
            inserted = 0
            for row in rows:
                cur = conn.execute(
                    insert_sql,
                    tuple(row.get(col) for col in _COLUMNS),
                )
                if cur.rowcount > 0:
                    inserted += 1
    finally:
        conn.close()

    result = {
        "fetched": len(rows),
        "inserted": inserted,
        "skipped_duplicated": len(rows) - inserted,
        "cursor": max((row["played_at"] for row in rows), default=cursor),
    }
    logger.info("Local sync: {}", result)
    return result
