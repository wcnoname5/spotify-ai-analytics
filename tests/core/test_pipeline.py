"""Tests for spotify_core.db.pipeline."""
import sqlite3
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from spotify_core.db.pipeline import init_history_db, import_json_to_db, sync_api_to_db, open_inspect_shell


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
def sample_json_dir(tmp_path):
    """Temp dir with one Streaming_test.json matching Spotify export format."""
    records = [
        {
            "ts": "2024-01-15T08:30:00Z",
            "platform": "Windows",
            "conn_country": "US",
            "master_metadata_track_name": "Bohemian Rhapsody",
            "master_metadata_album_artist_name": "Queen",
            "master_metadata_album_album_name": "A Night at the Opera",
            "ms_played": 354000,
            "spotify_track_uri": "spotify:track:001",
            "reason_start": "trackdone",
            "reason_end": "trackdone",
            "shuffle": False,
            "skipped": False,
        },
        {
            "ts": "2024-01-15T09:00:00Z",
            "platform": "iOS",
            "conn_country": "US",
            "master_metadata_track_name": "Stairway to Heaven",
            "master_metadata_album_artist_name": "Led Zeppelin",
            "master_metadata_album_album_name": "Led Zeppelin IV",
            "ms_played": 482000,
            "spotify_track_uri": "spotify:track:002",
            "reason_start": "trackdone",
            "reason_end": "trackdone",
            "shuffle": False,
            "skipped": False,
        },
    ]
    f = tmp_path / "Streaming_test.json"
    f.write_text(json.dumps(records))
    return tmp_path


@pytest.fixture
def history_db(tmp_path):
    """Initialized history DB."""
    db = tmp_path / "history.db"
    init_history_db(str(db))
    return db


@pytest.mark.unit
def test_import_json_inserts_rows(sample_json_dir, history_db):
    """import_json_to_db inserts rows from JSON files."""
    result = import_json_to_db(str(sample_json_dir), str(history_db))
    assert result["inserted"] == 2
    assert result["skipped_duplicated"] == 0
    assert result["skipped_parse_error"] == 0
    with sqlite3.connect(history_db) as conn:
        count = conn.execute("SELECT COUNT(*) FROM listening_history").fetchone()[0]
    assert count == 2


@pytest.mark.unit
def test_import_json_idempotent(sample_json_dir, history_db):
    """Importing the same files twice skips duplicates."""
    import_json_to_db(str(sample_json_dir), str(history_db))
    result = import_json_to_db(str(sample_json_dir), str(history_db))
    assert result["inserted"] == 0
    assert result["skipped_duplicated"] == 2


@pytest.mark.unit
def test_import_json_empty_dir(tmp_path, history_db):
    """import_json_to_db with empty dir returns zeros without raising."""
    result = import_json_to_db(str(tmp_path), str(history_db))
    assert result == {"inserted": 0, "skipped_duplicated": 0, "skipped_parse_error": 0}


@pytest.mark.unit
def test_import_json_source_field(sample_json_dir, history_db):
    """Imported rows have source='json_import'."""
    import_json_to_db(str(sample_json_dir), str(history_db))
    with sqlite3.connect(history_db) as conn:
        sources = {r[0] for r in conn.execute("SELECT DISTINCT source FROM listening_history")}
    assert sources == {"json_import"}


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


@pytest.mark.unit
def test_sync_api_no_token_raises(history_db, tmp_path):
    """sync_api_to_db raises RuntimeError when no token exists."""
    tokens_db = tmp_path / "tokens.db"
    with patch("spotify_core.db.pipeline.load_tokens", return_value=None):
        with pytest.raises(RuntimeError, match="Run OAuth flow first"):
            sync_api_to_db(str(history_db), str(tokens_db), "user1", "client_id", b"key")


@pytest.mark.unit
def test_sync_api_raises_when_token_absent_regardless_of_expiry(history_db, tmp_path):
    """sync_api_to_db raises if load_tokens returns None, no matter expiry state."""
    tokens_db = tmp_path / "tokens.db"
    with patch("spotify_core.db.pipeline.load_tokens", return_value=None):
        with pytest.raises(RuntimeError, match="Run OAuth flow first"):
            sync_api_to_db(str(history_db), str(tokens_db), "user1", "client_id", b"key")


@pytest.mark.unit
def test_open_inspect_shell_prints_cheatsheet(history_db, capsys):
    """open_inspect_shell prints the cheatsheet before launching sqlite3."""
    with patch("spotify_core.db.pipeline.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        open_inspect_shell(str(history_db))
    captured = capsys.readouterr()
    assert "listening_history" in captured.out
    assert "Top artists" in captured.out
    assert str(history_db) in captured.out


@pytest.mark.unit
def test_open_inspect_shell_calls_sqlite3(history_db):
    """open_inspect_shell invokes sqlite3 with the correct db path."""
    with patch("spotify_core.db.pipeline.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        open_inspect_shell(str(history_db))
    call_args = mock_run.call_args[0][0]
    assert call_args[0] == "sqlite3"
    assert str(history_db) in call_args
