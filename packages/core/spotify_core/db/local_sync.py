"""Incremental sync between the local SQLite cache and D1.

For listening history, D1 (via the Worker) remains the single source of
truth: this module only reads new rows through ``WorkerClient.get_tracks_since``
and upserts them into the local ``listening_history`` cache, cursored on
``MAX(played_at)``. Reports are the exception — they are written locally
first (see ``report_store.py``) and synced in both directions: unsynced
local rows are pushed to D1, and newer D1 rows are pulled down, cursored on
``MAX(generated_at)``.
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

    # Deferred import: report_store imports _EPOCH_ISO/_sql from this module,
    # so importing it at module top would create a circular import.
    from .report_store import pull_reports, push_unsynced

    reports_pushed = push_unsynced(db_path, worker)
    reports_pulled = pull_reports(db_path, worker)

    result = {
        "fetched": len(rows),
        "inserted": inserted,
        "skipped_duplicated": len(rows) - inserted,
        "cursor": max((row["played_at"] for row in rows), default=cursor),
        "reports_pushed": reports_pushed,
        "reports_pulled": reports_pulled,
    }
    logger.info("Local sync: {}", result)
    return result
