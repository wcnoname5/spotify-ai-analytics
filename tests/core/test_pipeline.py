"""Tests for spotify_core.db.pipeline.

The `import_json_to_db` and `open_inspect_shell` tests went with those functions:
the data export is parsed in TS now (see packages/shared-ts/export.test.ts) and
posted to the Worker, and the inspect shell needed a `sqlite3` binary.
"""
import sqlite3
import pytest
from unittest.mock import patch, MagicMock
from spotify_core.db.pipeline import (
    init_history_db,
    sync_api_to_db,
)


@pytest.mark.unit
def test_pipeline_init_creates_history_db(tmp_path):
    """init_history_db creates listening_history and sync_state tables."""
    db = tmp_path / "history.db"
    init_history_db(str(db))
    with sqlite3.connect(db) as conn:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
    assert "listening_history" in tables
    assert "sync_state" in tables


@pytest.mark.unit
def test_pipeline_init_idempotent(tmp_path):
    """Calling init_history_db twice does not raise."""
    db = tmp_path / "history.db"
    init_history_db(str(db))
    init_history_db(str(db))


@pytest.fixture
def history_db(tmp_path):
    """Initialized history DB."""
    db = tmp_path / "history.db"
    init_history_db(str(db))
    return db


def _make_recently_played_response(items):
    return {"items": items}


def _make_track_item(track_uri, track_name, artist_name, album_name, played_at, duration_ms=180000):
    return {
        "track": {
            "uri": track_uri,
            "name": track_name,
            "artists": [{"name": artist_name}],
            "album": {"name": album_name},
            "duration_ms": duration_ms,
        },
        "played_at": played_at,
    }


@pytest.mark.unit
def test_sync_api_inserts_rows(history_db, tmp_path):
    """sync_api_to_db inserts rows returned by the API."""
    tokens_db = tmp_path / "tokens.db"
    fake_key = b"fake_key"
    items = [
        _make_track_item("spotify:track:AAA", "Song A", "Artist A", "Album A", "2024-02-01T10:00:00.000Z"),
        _make_track_item("spotify:track:BBB", "Song B", "Artist B", "Album B", "2024-02-01T10:05:00.000Z"),
    ]

    with patch("spotify_core.db.pipeline.load_tokens", return_value={"access_token": "tok"}), \
         patch("spotify_core.db.pipeline.SpotifyClient") as MockClient:
        mock_instance = MagicMock()
        mock_instance.get_recently_played.return_value = _make_recently_played_response(items)
        MockClient.return_value.__enter__ = MagicMock(return_value=mock_instance)
        MockClient.return_value.__exit__ = MagicMock(return_value=False)

        result = sync_api_to_db(str(history_db), str(tokens_db), "user1", "client_id", fake_key)

    assert result["inserted"] == 2
    with sqlite3.connect(history_db) as conn:
        count = conn.execute("SELECT COUNT(*) FROM listening_history").fetchone()[0]
    assert count == 2


@pytest.mark.unit
def test_sync_api_updates_cursor(history_db, tmp_path):
    """sync_api_to_db writes the newest played_at as cursor in sync_state."""
    tokens_db = tmp_path / "tokens.db"
    fake_key = b"fake_key"
    items = [
        _make_track_item("spotify:track:CCC", "Song C", "Artist C", "Album C", "2024-02-01T10:00:00.000Z"),
    ]

    with patch("spotify_core.db.pipeline.load_tokens", return_value={"access_token": "tok"}), \
         patch("spotify_core.db.pipeline.SpotifyClient") as MockClient:
        mock_instance = MagicMock()
        mock_instance.get_recently_played.return_value = _make_recently_played_response(items)
        MockClient.return_value.__enter__ = MagicMock(return_value=mock_instance)
        MockClient.return_value.__exit__ = MagicMock(return_value=False)

        result = sync_api_to_db(str(history_db), str(tokens_db), "user1", "client_id", fake_key)

    assert result["cursor_ms"] > 0
    with sqlite3.connect(history_db) as conn:
        row = conn.execute("SELECT value FROM sync_state WHERE key='last_played_at_ms'").fetchone()
    assert row is not None
    assert row[0] == result["cursor_ms"]


@pytest.mark.unit
def test_sync_api_idempotent(history_db, tmp_path):
    """sync_api_to_db with same items twice inserts 0 on second call."""
    tokens_db = tmp_path / "tokens.db"
    fake_key = b"fake_key"
    items = [
        _make_track_item("spotify:track:DDD", "Song D", "Artist D", "Album D", "2024-02-01T11:00:00.000Z"),
    ]

    def run_sync():
        with patch("spotify_core.db.pipeline.load_tokens", return_value={"access_token": "tok"}), \
             patch("spotify_core.db.pipeline.SpotifyClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.get_recently_played.return_value = _make_recently_played_response(items)
            MockClient.return_value.__enter__ = MagicMock(return_value=mock_instance)
            MockClient.return_value.__exit__ = MagicMock(return_value=False)
            return sync_api_to_db(str(history_db), str(tokens_db), "user1", "client_id", fake_key)

    first = run_sync()
    second = run_sync()
    assert first["inserted"] == 1
    assert second["inserted"] == 0
    assert second["cursor_ms"] == first["cursor_ms"]


