"""Smoke test for WorkerClient — all network calls are mocked."""
from unittest.mock import MagicMock

import pytest

from spotify_core.db.worker_client import WorkerClient

BASE_URL = "https://worker.example.workers.dev"
AUTH_TOKEN = "test-auth-token"


def _ok_response(body: dict) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json.return_value = body
    return resp


@pytest.mark.unit
def test_get_cursor_sends_auth_header_and_parses_response():
    """get_cursor() GETs /api/cursor with a Bearer header and returns the ms value."""
    mock_http = MagicMock()
    mock_http.request.return_value = _ok_response({"last_played_at_ms": 1700000000000})

    client = WorkerClient(BASE_URL, AUTH_TOKEN, http_client=mock_http)
    result = client.get_cursor()

    mock_http.request.assert_called_once()
    args, kwargs = mock_http.request.call_args
    assert args[0] == "GET"
    assert args[1] == BASE_URL + "/api/cursor"
    assert kwargs["headers"]["Authorization"] == f"Bearer {AUTH_TOKEN}"
    assert result == 1700000000000


@pytest.mark.unit
def test_post_tracks_sends_json_body_and_returns_inserted_count():
    """post_tracks() POSTs /api/tracks with {"tracks": rows} and returns the inserted count."""
    mock_http = MagicMock()
    mock_http.request.return_value = _ok_response({"inserted": 2})

    client = WorkerClient(BASE_URL, AUTH_TOKEN, http_client=mock_http)
    rows = [{"track_id": "t1"}, {"track_id": "t2"}]
    result = client.post_tracks(rows)

    args, kwargs = mock_http.request.call_args
    assert args[0] == "POST"
    assert args[1] == BASE_URL + "/api/tracks"
    assert kwargs["headers"]["Authorization"] == f"Bearer {AUTH_TOKEN}"
    assert kwargs["json"] == {"tracks": rows}
    assert result == 2
