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

def init_history_db(db_path: Union[str, Path]) -> None:
    """Create history.db by applying every migration. Idempotent.

    The app's own runner (`apps/tauri/src/lib/migrations.ts`) tracks
    `PRAGMA user_version` so it only applies what is new. This one re-applies the
    whole set, which is equivalent while every statement is
    `CREATE ... IF NOT EXISTS` — and stops being equivalent the moment a
    migration contains an ALTER. Point this at the shared runner if that happens.

    An ad-hoc `_migrate_history_db` used to live here, ALTERing in the six
    export-only columns. They are in 0001's CREATE now, so a fresh database gets
    them and there is nothing left to patch up.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        for ddl in HISTORY_DDL:
            conn.execute(ddl)
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

def get_connection(db_path: Union[str, Path]) -> sqlite3.Connection:
    """Open a connection with sensible defaults (WAL mode, foreign keys on).

    Caller is responsible for closing the connection (use as context manager).
    """
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row   # allows dict-like column access
    return conn
