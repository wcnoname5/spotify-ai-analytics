"""Smoke tests for sync_api_to_worker — WorkerClient and SpotifyClient are mocked."""
from unittest.mock import MagicMock, patch

import pytest

from spotify_core.db.pipeline import sync_api_to_worker

USER_ID = "default"
CLIENT_ID = "test-client-id"
FERNET_KEY = b"0" * 32  # not a real Fernet key, but the constructor is never exercised for real decrypt here

ENCRYPTED_ROW = {
    "access_token": "enc-access",
    "refresh_token": "enc-refresh",
    "expires_at": "2999-01-01T00:00:00+00:00",
    "scopes": "user-read-recently-played",
}

API_RESPONSE = {
    "items": [
        {
            "track": {
                "uri": "spotify:track:abc",
                "name": "Song A",
                "duration_ms": 210000,
                "artists": [{"name": "Artist A"}],
                "album": {"name": "Album A"},
            },
            "played_at": "2024-01-15T08:30:00Z",
        }
    ]
}


@pytest.mark.unit
def test_sync_api_to_worker_happy_path(tmp_path):
    """Tracks are posted, cursor advances, and tokens are posted back."""
    worker = MagicMock()
    worker.get_tokens.return_value = ENCRYPTED_ROW
    worker.get_cursor.return_value = 0
    worker.post_tracks.return_value = 1

    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = False
    mock_client.get_recently_played.return_value = API_RESPONSE

    with patch("spotify_core.db.pipeline.SpotifyClient", return_value=mock_client):
        result = sync_api_to_worker(
            tokens_scratch_db_path=str(tmp_path / "tokens.db"),
            user_id=USER_ID,
            client_id=CLIENT_ID,
            fernet_key=FERNET_KEY,
            worker=worker,
        )

    worker.get_tokens.assert_called_once_with(USER_ID)
    worker.post_tracks.assert_called_once()
    posted_rows = worker.post_tracks.call_args[0][0]
    assert posted_rows[0]["track_id"] == "spotify:track:abc"
    assert "played_at_ms" not in posted_rows[0]

    expected_cursor_ms = 1705307400000  # 2024-01-15T08:30:00Z in epoch ms
    worker.post_cursor.assert_called_once_with(expected_cursor_ms)
    worker.post_tokens.assert_called_once()
    assert worker.post_tokens.call_args[0][0] == USER_ID

    assert result == {
        "inserted": 1,
        "skipped_parse_error": 0,
        "cursor_ms": expected_cursor_ms,
    }


@pytest.mark.unit
def test_sync_api_to_worker_raises_when_no_tokens_in_worker(tmp_path):
    """No stored token row in the Worker raises a clear RuntimeError."""
    worker = MagicMock()
    worker.get_tokens.return_value = None

    with pytest.raises(RuntimeError, match="No OAuth tokens found"):
        sync_api_to_worker(
            tokens_scratch_db_path=str(tmp_path / "tokens.db"),
            user_id=USER_ID,
            client_id=CLIENT_ID,
            fernet_key=FERNET_KEY,
            worker=worker,
        )

    worker.post_tracks.assert_not_called()
    worker.post_cursor.assert_not_called()
    worker.post_tokens.assert_not_called()
