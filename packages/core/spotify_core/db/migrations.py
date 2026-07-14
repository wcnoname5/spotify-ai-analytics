"""Database initialization and migration utilities."""
import sqlite3
from loguru import logger
from pathlib import Path
from typing import Union
from .schema import ALL_DDL, HISTORY_DDL, SPOTIFY_TOKENS_DDL

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
            # CREATE TABLE statements are idempotent, so this won't overwrite existing tables or data.
            conn.execute(ddl)
        conn.commit()

    logger.info("Database initialized at {}", db_path)

# These are fields only in streaming history exports, but not in the API data.
_HISTORY_COLUMNS = {
    "platform":     "TEXT",
    "conn_country": "TEXT",
    "reason_start": "TEXT",
    "reason_end":   "TEXT",
    "shuffle":      "INTEGER", # Bool, use INTEGER with 0/1 in SQLite.
    "skipped":      "INTEGER", # Bool.
}


def _migrate_history_db(conn: sqlite3.Connection) -> None:
    """Add any missing columns to listening_history (idempotent)."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(listening_history)")}
    for col, col_type in _HISTORY_COLUMNS.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE listening_history ADD COLUMN {col} {col_type}")
            logger.info("Migration: added column {} {} to listening_history", col, col_type)


def init_history_db(db_path: Union[str, Path]) -> None:
    """Create history.db with listening_history, sync_state, and index.
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
        _migrate_history_db(conn)
        conn.commit()

    logger.info("History database initialized at {}", db_path)


def init_tokens_db(db_path: Union[str, Path]) -> None:
    """Create tokens.db with the spotify_tokens table if it doesn't exist.
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
        conn.execute(SPOTIFY_TOKENS_DDL)
        conn.commit()

    logger.info("Tokens database initialized at {}", db_path)

def init_meta_table(db_path: Union[str, Path]) -> None:
    """Create the local-only ``meta`` key/value table if it doesn't exist.

    This table is local-cache bookkeeping only (e.g. the local-sync cursor)
    — it is NOT part of the generated D1 schema (see ``schema.py``) and must
    never be added there. Safe to call multiple times (idempotent).

    Args:
        db_path: Path to the SQLite database file. Parent directory will be
                 created automatically if it does not exist.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)"
        )
        conn.commit()

    logger.info("Meta table initialized at {}", db_path)


def get_connection(db_path: Union[str, Path]) -> sqlite3.Connection:
    """Open a connection with sensible defaults (WAL mode, foreign keys on).

    Caller is responsible for closing the connection (use as context manager).
    """
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row   # allows dict-like column access
    return conn
