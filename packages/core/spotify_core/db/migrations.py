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

    logger.info(f"Database initialized at {db_path}")

# These are fields only in streaming history exports, but not in the API data.
_HISTORY_COLUMNS = {
    "platform":     "TEXT",
    "conn_country": "TEXT",
    "reason_start": "TEXT",
    "reason_end":   "TEXT",
    "shuffle":      "INTEGER", # Bool, but bool is not a native SQLite type, so use INTEGER with 0/1 values.
    "skipped":      "INTEGER", # Bool, but bool is not a native SQLite type, so use INTEGER with 0/1 values.
}


def _migrate_history_db(conn: sqlite3.Connection) -> None:
    """Add any missing columns to listening_history (idempotent)."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(listening_history)")}
    for col, col_type in _HISTORY_COLUMNS.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE listening_history ADD COLUMN {col} {col_type}")
            logger.info("Migration: added column %s %s to listening_history", col, col_type)


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
        _migrate_history_db(conn)
        conn.commit()

    logger.info("History database initialized at %s", db_path)


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

    logger.info("Tokens database initialized at %s", db_path)

def init_ltm_db(db_path: Union[str, Path]) -> None:
    """Create ltm.db with the LangGraph SqliteStore schema.

    LangGraph's SqliteStore manages its own schema. This helper opens the store
    once so its tables are materialised on disk, making the file usable by the
    MCP memory tools without waiting for the first put/get to lazily create them.
    Safe to call multiple times (idempotent).

    Args:
        db_path: Path to the SQLite database file. Parent directory will be
                 created automatically if it does not exist.
    """
    from langgraph.store.sqlite import SqliteStore

    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # Entering the context manager runs SqliteStore.setup() which creates its tables.
    with SqliteStore.from_conn_string(str(db_path)) as store:
        # Some langgraph versions defer table creation until setup() is called explicitly.
        if hasattr(store, "setup"):
            try:
                store.setup()
            except Exception:
                # setup() may not be exposed or may already have run during __enter__.
                pass

    logger.info("LTM database initialized at %s", db_path)


def get_connection(db_path: Union[str, Path]) -> sqlite3.Connection:
    """Open a connection with sensible defaults (WAL mode, foreign keys on).

    Caller is responsible for closing the connection (use as context manager).
    """
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row   # allows dict-like column access
    return conn
