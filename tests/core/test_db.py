"""Tests for packages/core/spotify_core/db."""
import pytest
import sqlite3
from pathlib import Path
from spotify_core.db.migrations import init_db, init_history_db, get_connection
from spotify_core.db.schema import ALL_DDL, LISTENING_HISTORY_DDL, SPOTIFY_TOKENS_DDL, HISTORY_DDL, SYNC_STATE_DDL


@pytest.mark.unit
def test_init_db_creates_file(tmp_path):
    """init_db creates the DB file and parent directory."""
    db_path = tmp_path / "subdir" / "test.db"
    assert not db_path.exists()
    init_db(db_path)
    assert db_path.exists()


@pytest.mark.unit
def test_init_db_idempotent(tmp_path):
    """Calling init_db twice does not raise (IF NOT EXISTS semantics)."""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    init_db(db_path)  # second call must not raise


@pytest.mark.unit
def test_listening_history_table_created(tmp_path):
    """listening_history table exists with correct columns after init."""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    with get_connection(db_path) as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(listening_history)")}
    expected = {"id", "track_id", "track_name", "artist_name", "album_name",
                "played_at", "ms_played", "source"}
    assert expected.issubset(cols)


@pytest.mark.unit
def test_spotify_tokens_table_created(tmp_path):
    """spotify_tokens table exists with correct columns after init."""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    with get_connection(db_path) as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(spotify_tokens)")}
    expected = {"user_id", "access_token", "refresh_token", "expires_at", "scopes"}
    assert expected.issubset(cols)


@pytest.mark.unit
def test_insert_and_read_listening_history(tmp_path):
    """Can insert a row and read it back from listening_history."""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    with get_connection(db_path) as conn:
        conn.execute(
            "INSERT INTO listening_history (id, track_id, track_name, artist_name, played_at, source) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("hash123", "track001", "Test Song", "Test Artist", "2024-01-15T08:30:00", "api")
        )
        conn.commit()
        row = conn.execute("SELECT * FROM listening_history WHERE id = ?", ("hash123",)).fetchone()
    assert row["track_name"] == "Test Song"
    assert row["source"] == "api"


@pytest.mark.unit
def test_insert_and_read_spotify_tokens(tmp_path):
    """Can insert a token row and read it back from spotify_tokens."""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    with get_connection(db_path) as conn:
        conn.execute(
            "INSERT INTO spotify_tokens (user_id, access_token, refresh_token, expires_at) "
            "VALUES (?, ?, ?, ?)",
            ("user1", "encrypted_access", "encrypted_refresh", "2024-12-31T23:59:59")
        )
        conn.commit()
        row = conn.execute("SELECT * FROM spotify_tokens WHERE user_id = ?", ("user1",)).fetchone()
    assert row["access_token"] == "encrypted_access"


@pytest.mark.unit
def test_source_constraint(tmp_path):
    """source column CHECK constraint rejects invalid values."""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    with get_connection(db_path) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO listening_history (id, track_id, played_at, source) VALUES (?, ?, ?, ?)",
                ("h2", "t2", "2024-01-01T00:00:00", "invalid_source")
            )


@pytest.mark.unit
def test_get_connection_row_factory(tmp_path):
    """get_connection sets row_factory so columns are accessible by name."""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        conn.execute(
            "INSERT INTO listening_history (id, track_id, played_at) VALUES (?, ?, ?)",
            ("h3", "t3", "2024-01-01T00:00:00")
        )
        conn.commit()
        row = conn.execute("SELECT id, track_id FROM listening_history").fetchone()
        assert row["id"] == "h3"
        assert row["track_id"] == "t3"
    finally:
        conn.close()


@pytest.mark.unit
def test_history_ddl_contains_sync_state(tmp_path):
    """HISTORY_DDL creates sync_state table."""
    db_path = tmp_path / "test.db"
    with sqlite3.connect(db_path) as conn:
        for ddl in HISTORY_DDL:
            conn.execute(ddl)
    with sqlite3.connect(db_path) as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(sync_state)")}
    assert {"key", "value"}.issubset(cols)


@pytest.mark.unit
def test_init_history_db_creates_tables(tmp_path):
    """init_history_db creates listening_history and sync_state."""
    db_path = tmp_path / "history.db"
    init_history_db(db_path)
    with sqlite3.connect(db_path) as conn:
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
    assert "listening_history" in tables
    assert "sync_state" in tables


@pytest.mark.unit
def test_init_history_db_idempotent(tmp_path):
    """Calling init_history_db twice does not raise."""
    db_path = tmp_path / "history.db"
    init_history_db(db_path)
    init_history_db(db_path)
