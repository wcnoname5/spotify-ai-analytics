"""Tests for scripts/setup.py — verifies it creates all DBs from a clean slate.

Mocks the OAuth PKCE flow so the test can run without a browser.
"""
import json
import sqlite3
import sys
import importlib
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"


@pytest.fixture
def setup_env(tmp_path, monkeypatch):
    """Run setup.py against an empty tmp_path with mocked OAuth.

    Returns a dict with the resolved DB paths and the JSON dir used.
    """
    history_db = tmp_path / "history.db"
    tokens_db = tmp_path / "tokens.db"
    ltm_db = tmp_path / "ltm.db"
    json_dir = tmp_path / "spotify_history"
    json_dir.mkdir()

    # Minimal valid Streaming_History_Audio JSON record
    record = {
        "ts": "2024-01-01T00:00:00Z",
        "ms_played": 12345,
        "master_metadata_track_name": "Test Track",
        "master_metadata_album_artist_name": "Test Artist",
        "master_metadata_album_album_name": "Test Album",
        "spotify_track_uri": "spotify:track:abcdefg",
        "platform": "test",
        "conn_country": "US",
        "reason_start": "trackdone",
        "reason_end": "trackdone",
        "shuffle": False,
        "skipped": False,
    }
    (json_dir / "Streaming_History_Audio_2024.json").write_text(json.dumps([record]))

    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "test_client_id")
    monkeypatch.setenv("SPOTIFY_USER_ID", "test_user")
    # Provide a Fernet key so setup.py doesn't try to mutate .env
    from cryptography.fernet import Fernet
    monkeypatch.setenv("TOKEN_ENCRYPT_KEY", Fernet.generate_key().decode())

    # Mock OAuth: never open a browser
    fake_token_data = {
        "access_token": "fake_access",
        "refresh_token": "fake_refresh",
        "expires_in": 3600,
        "scope": "user-read-recently-played",
    }
    import spotify_core.spotify_client.auth as auth_mod
    monkeypatch.setattr(auth_mod, "run_pkce_flow", lambda client_id: fake_token_data)

    # Inject sys.argv as setup.py uses argparse
    argv = [
        "setup.py",
        "--user-id", "test_user",
        "--db", str(history_db),
        "--tokens-db", str(tokens_db),
        "--ltm-db", str(ltm_db),
        "--json-dir", str(json_dir),
    ]
    monkeypatch.setattr(sys, "argv", argv)

    # Make scripts/ importable
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))

    # Re-import setup fresh each test
    if "setup" in sys.modules:
        del sys.modules["setup"]
    setup_mod = importlib.import_module("setup")
    setup_mod.main()

    return {
        "history_db": history_db,
        "tokens_db": tokens_db,
        "ltm_db": ltm_db,
        "json_dir": json_dir,
    }


def test_setup_creates_history_db_with_table(setup_env):
    db = setup_env["history_db"]
    assert db.exists(), "history.db should be created"
    with sqlite3.connect(db) as conn:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
    assert "listening_history" in tables
    assert "sync_state" in tables


def test_setup_creates_tokens_db_with_table(setup_env):
    db = setup_env["tokens_db"]
    assert db.exists(), "tokens.db should be created"
    with sqlite3.connect(db) as conn:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
    assert "spotify_tokens" in tables


def test_setup_creates_ltm_db(setup_env):
    db = setup_env["ltm_db"]
    assert db.exists(), "ltm.db should be created"
    # SqliteStore writes its own schema on init — at least one table should exist
    with sqlite3.connect(db) as conn:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )]
    assert tables, "ltm.db should contain at least one table after init"


def test_setup_imports_json_into_history_db(setup_env):
    db = setup_env["history_db"]
    with sqlite3.connect(db) as conn:
        count = conn.execute("SELECT COUNT(*) FROM listening_history").fetchone()[0]
    assert count == 1, "JSON record should be imported into history.db"


def test_setup_stores_tokens_for_user(setup_env):
    db = setup_env["tokens_db"]
    with sqlite3.connect(db) as conn:
        row = conn.execute(
            "SELECT user_id FROM spotify_tokens WHERE user_id = ?", ("test_user",)
        ).fetchone()
    assert row is not None, "tokens for test_user should be saved"


def test_setup_is_idempotent(setup_env, monkeypatch):
    """Re-running setup.py against the same paths must not fail or wipe data."""
    # Already ran once via the fixture; run main() a second time
    import setup as setup_mod
    setup_mod.main()

    db = setup_env["history_db"]
    with sqlite3.connect(db) as conn:
        count = conn.execute("SELECT COUNT(*) FROM listening_history").fetchone()[0]
    assert count == 1, "Re-run should not duplicate or wipe rows"
