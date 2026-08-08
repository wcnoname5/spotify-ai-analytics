"""Local-first report persistence: save with synced=0, push to the Worker,
pull D1 rows behind a generated_at cursor. Outbox = the unsynced rows
themselves; INSERT OR IGNORE + uuid ids make every direction idempotent."""
from importlib.resources import files
from pathlib import Path
from typing import Optional, Union

from loguru import logger

from .migrations import get_connection, init_history_db
from .worker_client import WorkerClient

_EPOCH_ISO = "1970-01-01T00:00:00Z"


def _sql(name: str) -> str:
    """Load a query body from db/sql/<name>.sql."""
    return files("spotify_core.db.sql").joinpath(f"{name}.sql").read_text()

REPORT_COLUMNS = (
    "id", "style", "period_type", "start_date", "end_date",
    "provider", "model", "generated_at", "revision_count", "report_text",
)


def save_report_local(db_path: Union[str, Path], row: dict, synced: int = 0) -> None:
    """INSERT OR IGNORE one report row into the local db."""
    init_history_db(db_path)
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute(_sql("insert_report"),
                         tuple(row[c] for c in REPORT_COLUMNS) + (synced,))
    finally:
        conn.close()


def push_unsynced(db_path: Union[str, Path], worker: WorkerClient) -> int:
    """POST every synced=0 row to the Worker; mark each synced on success."""
    conn = get_connection(db_path)
    try:
        rows = [dict(r) for r in conn.execute(_sql("unsynced_reports")).fetchall()]
        for row in rows:
            worker.post_report(row)
            with conn:
                conn.execute(_sql("mark_report_synced"), (row["id"],))
        if rows:
            logger.info("Pushed {} report(s) to Worker", len(rows))
        return len(rows)
    finally:
        conn.close()


def pull_reports(db_path: Union[str, Path], worker: WorkerClient) -> int:
    """Pull D1 report rows newer than the local cursor; store them synced=1."""
    init_history_db(db_path)
    conn = get_connection(db_path)
    try:
        with conn:
            cursor = conn.execute(_sql("max_report_generated_at")).fetchone()["c"] or _EPOCH_ISO
            inserted = 0
            for row in worker.get_reports_since(cursor):
                cur = conn.execute(_sql("insert_report"),
                                   tuple(row.get(c) for c in REPORT_COLUMNS) + (1,))
                inserted += cur.rowcount
        return inserted
    finally:
        conn.close()


def list_reports(db_path: Union[str, Path]) -> list[dict]:
    """Report metadata (no text), newest first."""
    conn = get_connection(db_path)
    try:
        return [dict(r) for r in conn.execute(_sql("list_reports")).fetchall()]
    finally:
        conn.close()


def get_report(db_path: Union[str, Path], report_id: str) -> Optional[dict]:
    """One full report row (with text and synced) by id, or None."""
    conn = get_connection(db_path)
    try:
        row = conn.execute(_sql("get_report"), (report_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()
