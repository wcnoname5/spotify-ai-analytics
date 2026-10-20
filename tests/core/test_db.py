"""Tests for packages/core/spotify_core/db."""
import sqlite3

import pytest

from spotify_core.db.migrations import get_connection
from spotify_core.db.schema import all_ddl


def test_migrations_create_the_tables(history_db):
    with get_connection(history_db()) as conn:
        def cols(table):
            return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}

        assert {"id", "track_id", "track_name", "artist_name", "album_name",
                "played_at", "ms_played", "source"} <= cols("listening_history")
        assert {"user_id", "access_token", "refresh_token", "expires_at", "scopes"} <= cols("spotify_tokens")
        assert {"key", "value"} <= cols("sync_state")


def test_migrations_are_rerunnable(history_db):
    """cloudflare.rs re-applies every migration on each deploy, which is only
    safe while every statement is `IF NOT EXISTS`."""
    db = history_db()
    with sqlite3.connect(db) as conn:
        for ddl in all_ddl():
            conn.execute(ddl)


def test_source_constraint(history_db):
    """source column CHECK constraint rejects invalid values."""
    with get_connection(history_db()) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO listening_history (id, track_id, played_at, source) VALUES (?, ?, ?, ?)",
                ("h2", "t2", "2024-01-01T00:00:00", "invalid_source")
            )


def test_get_connection_row_factory(history_db):
    """get_connection sets row_factory so columns are accessible by name."""
    db = history_db([{"id": "h3", "track_id": "t3", "played_at": "2024-01-01T00:00:00Z", "ms_played": 0}])
    conn = get_connection(db)
    try:
        row = conn.execute("SELECT id, track_id FROM listening_history").fetchone()
        assert row["id"] == "h3"
        assert row["track_id"] == "t3"
    finally:
        conn.close()
