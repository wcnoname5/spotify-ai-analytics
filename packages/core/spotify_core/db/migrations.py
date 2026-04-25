"""Database initialization and migration utilities."""
import sqlite3
import logging
from pathlib import Path
from typing import Union
from .schema import ALL_DDL, HISTORY_DDL

logger = logging.getLogger(__name__)


def init_db(db_path: Union[str, Path]) -> None:
    """Create all tables and indexes if they don't exist.

    Safe to call multiple times (uses CREATE TABLE IF NOT EXISTS).

    Args:
        db_path: Path to the SQLite database file. Parent directory will be
                 created automatically if it does not exist.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")   # better concurrent read performance
        conn.execute("PRAGMA foreign_keys=ON")
        for ddl in ALL_DDL:
            conn.execute(ddl)
        conn.commit()

    logger.info(f"Database initialized at {db_path}")


def init_history_db(db_path: Union[str, Path]) -> None:
    """Create history.db with listening_history, sync_state, and index.

    Does NOT create spotify_tokens — that table lives in tokens.db,
    owned by spotify_client/token_store.py.
    Safe to call multiple times (idempotent).

    Args:
        db_path: Path to the SQLite database file. Parent directory will be
                 created automatically if it does not exist.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        for ddl in HISTORY_DDL:
            conn.execute(ddl)
        conn.commit()

    logger.info("History database initialized at %s", db_path)


def get_connection(db_path: Union[str, Path]) -> sqlite3.Connection:
    """Open a connection with sensible defaults (WAL mode, foreign keys on).

    Caller is responsible for closing the connection (use as context manager).
    """
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row   # allows dict-like column access
    return conn
