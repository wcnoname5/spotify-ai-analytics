"""Unit tests for SpotifyClient — all network calls are mocked."""
from unittest.mock import MagicMock, patch, call
import pytest
from cryptography.fernet import Fernet

from spotify_core.db.migrations import init_db
from spotify_core.spotify_client.token_store import save_tokens
from spotify_core.spotify_client.client import SpotifyClient, BASE_URL

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FERNET_KEY = Fernet.generate_key()
USER_ID = "test_user"
CLIENT_ID = "test_client_id"


def _make_token_dict(expires_in: int = 3600) -> dict:
    return {
        "access_token": "fake_access_token",
        "refresh_token": "fake_refresh_token",
        "expires_in": expires_in,
        "scope": "user-read-recently-played",
    }


def _make_client(tmp_path, http_client: MagicMock) -> SpotifyClient:
    """Create a SpotifyClient backed by a temp DB with a valid token stored."""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    save_tokens(db_path, USER_ID, _make_token_dict(), FERNET_KEY)
    return SpotifyClient(
        db_path=db_path,
        user_id=USER_ID,
        client_id=CLIENT_ID,
        fernet_key=FERNET_KEY,
        http_client=http_client,
    )


def _ok_response(body: dict | None = None) -> MagicMock:
    """Build a mock httpx.Response with status 200."""
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json.return_value = body or {}
    return resp


# ---------------------------------------------------------------------------
# Test 1: get_current_user sends GET /me with Authorization header
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_get_current_user_sends_auth_header(tmp_path):
    """get_current_user calls GET /me with a Bearer Authorization header."""
    mock_http = MagicMock()
    mock_http.request.return_value = _ok_response({"id": USER_ID})

    client = _make_client(tmp_path, mock_http)
    result = client.get_current_user()

    mock_http.request.assert_called_once()
    args, kwargs = mock_http.request.call_args
    assert args[0] == "GET"
    assert args[1] == BASE_URL + "/me"
    assert kwargs["headers"]["Authorization"].startswith("Bearer ")
    assert result == {"id": USER_ID}


# ---------------------------------------------------------------------------
# Test 2: get_recently_played passes limit param correctly
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_get_recently_played_passes_limit(tmp_path):
    """get_recently_played passes limit (and optional after) as query params."""
    mock_http = MagicMock()
    mock_http.request.return_value = _ok_response({"items": []})

    client = _make_client(tmp_path, mock_http)
    client.get_recently_played(limit=25, after=1700000000000)

    _, kwargs = mock_http.request.call_args
    assert kwargs["params"]["limit"] == 25
    assert kwargs["params"]["after"] == 1700000000000


# ---------------------------------------------------------------------------
# Test 3: get_top_items passes type and time_range correctly
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_get_top_items_passes_type_and_time_range(tmp_path):
    """get_top_items encodes type in the URL path and time_range as a param."""
    mock_http = MagicMock()
    mock_http.request.return_value = _ok_response({"items": []})

    client = _make_client(tmp_path, mock_http)
    client.get_top_items("artists", time_range="short_term", limit=10)

    args, kwargs = mock_http.request.call_args
    assert args[1] == BASE_URL + "/me/top/artists"
    assert kwargs["params"]["time_range"] == "short_term"
    assert kwargs["params"]["limit"] == 10


# ---------------------------------------------------------------------------
# Test 4: play sends PUT /me/player/play with correct body
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_play_sends_correct_body(tmp_path):
    """play() sends PUT /me/player/play with uris in the JSON body."""
    mock_http = MagicMock()
    resp = _ok_response()
    resp.status_code = 204
    mock_http.request.return_value = resp

    client = _make_client(tmp_path, mock_http)
    uris = ["spotify:track:abc123", "spotify:track:def456"]
    client.play(device_id="dev1", uris=uris)

    args, kwargs = mock_http.request.call_args
    assert args[0] == "PUT"
    assert args[1] == BASE_URL + "/me/player/play"
    assert kwargs["json"]["uris"] == uris
    assert kwargs["params"]["device_id"] == "dev1"


# ---------------------------------------------------------------------------
# Test 5: pause sends PUT /me/player/pause
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_pause_sends_put_pause(tmp_path):
    """pause() sends PUT /me/player/pause."""
    mock_http = MagicMock()
    resp = _ok_response()
    resp.status_code = 204
    mock_http.request.return_value = resp

    client = _make_client(tmp_path, mock_http)
    client.pause()

    args, _ = mock_http.request.call_args
    assert args[0] == "PUT"
    assert args[1] == BASE_URL + "/me/player/pause"


# ---------------------------------------------------------------------------
# Test 6: set_volume sends PUT /me/player/volume with volume_percent
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_set_volume_passes_volume_percent(tmp_path):
    """set_volume() sends PUT /me/player/volume with volume_percent param."""
    mock_http = MagicMock()
    resp = _ok_response()
    resp.status_code = 204
    mock_http.request.return_value = resp

    client = _make_client(tmp_path, mock_http)
    client.set_volume(42)

    args, kwargs = mock_http.request.call_args
    assert args[0] == "PUT"
    assert args[1] == BASE_URL + "/me/player/volume"
    assert kwargs["params"]["volume_percent"] == 42


# ---------------------------------------------------------------------------
# Test 7: _get_access_token auto-refreshes when token is expired
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_auto_refresh_when_token_expired(tmp_path):
    """_get_access_token triggers refresh POST and calls save_tokens when expired."""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    save_tokens(db_path, USER_ID, _make_token_dict(), FERNET_KEY)

    mock_http = MagicMock()

    # First call: token refresh POST
    refresh_response = MagicMock()
    refresh_response.status_code = 200
    refresh_response.raise_for_status = MagicMock()
    refresh_response.json.return_value = {
        "access_token": "new_access_token",
        "refresh_token": "new_refresh_token",
        "expires_in": 3600,
        "scope": "user-read-recently-played",
    }

    # Second call: actual API request (GET /me)
    api_response = _ok_response({"id": USER_ID})

    mock_http.post = MagicMock(return_value=refresh_response)
    mock_http.request = MagicMock(return_value=api_response)

    client = SpotifyClient(
        db_path=db_path,
        user_id=USER_ID,
        client_id=CLIENT_ID,
        fernet_key=FERNET_KEY,
        http_client=mock_http,
    )

    with patch(
        "spotify_core.spotify_client.client.is_token_expired", return_value=True
    ), patch(
        "spotify_core.spotify_client.client.save_tokens"
    ) as mock_save:
        token = client._get_access_token()

    # The refresh POST must have been sent to the token endpoint
    mock_http.post.assert_called_once()
    post_args, post_kwargs = mock_http.post.call_args
    assert "accounts.spotify.com/api/token" in post_args[0]
    assert post_kwargs["data"]["grant_type"] == "refresh_token"
    assert post_kwargs["data"]["client_id"] == CLIENT_ID

    # save_tokens must have been called with the new token dict
    mock_save.assert_called_once()
    saved_token_dict = mock_save.call_args[0][2]
    assert saved_token_dict["access_token"] == "new_access_token"


# ---------------------------------------------------------------------------
# Test 8: search passes q, type, and limit params
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_search_passes_correct_params(tmp_path):
    """search() passes q, type (comma-joined), and limit as query params."""
    mock_http = MagicMock()
    mock_http.request.return_value = _ok_response({"tracks": {"items": []}})

    client = _make_client(tmp_path, mock_http)
    client.search("bohemian rhapsody", types=("track", "artist"), limit=15)

    _, kwargs = mock_http.request.call_args
    assert kwargs["params"]["q"] == "bohemian rhapsody"
    assert kwargs["params"]["type"] == "track,artist"
    assert kwargs["params"]["limit"] == 15


# ---------------------------------------------------------------------------
# Test 9: add_to_queue sends POST /me/player/queue with uri param
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_add_to_queue_sends_uri_param(tmp_path):
    """add_to_queue() sends POST /me/player/queue with the uri param."""
    mock_http = MagicMock()
    resp = _ok_response()
    resp.status_code = 204
    mock_http.request.return_value = resp

    client = _make_client(tmp_path, mock_http)
    client.add_to_queue("spotify:track:xyz789")

    args, kwargs = mock_http.request.call_args
    assert args[0] == "POST"
    assert args[1] == BASE_URL + "/me/player/queue"
    assert kwargs["params"]["uri"] == "spotify:track:xyz789"


# ---------------------------------------------------------------------------
# Test 10: skip_to_next sends POST /me/player/next
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_skip_to_next_sends_post(tmp_path):
    """skip_to_next() sends POST /me/player/next."""
    mock_http = MagicMock()
    resp = _ok_response()
    resp.status_code = 204
    mock_http.request.return_value = resp

    client = _make_client(tmp_path, mock_http)
    client.skip_to_next()

    args, _ = mock_http.request.call_args
    assert args[0] == "POST"
    assert args[1] == BASE_URL + "/me/player/next"


# ---------------------------------------------------------------------------
# Bonus test: create_playlist sends POST with correct body
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_create_playlist_sends_correct_body(tmp_path):
    """create_playlist() sends POST /me/playlists (deprecated /users/{id}/playlists endpoint removed)."""
    mock_http = MagicMock()
    mock_http.request.return_value = _ok_response({"id": "playlist123"})

    client = _make_client(tmp_path, mock_http)
    result = client.create_playlist(USER_ID, "My Playlist", public=True, description="test")

    args, kwargs = mock_http.request.call_args
    assert args[0] == "POST"
    assert args[1] == BASE_URL + "/me/playlists"
    assert kwargs["json"]["name"] == "My Playlist"
    assert kwargs["json"]["public"] is True
    assert kwargs["json"]["description"] == "test"
    assert result == {"id": "playlist123"}


# ---------------------------------------------------------------------------
# Bonus test: add_tracks_to_playlist sends POST with uris body
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_add_tracks_to_playlist_sends_uris(tmp_path):
    """add_tracks_to_playlist() sends POST /playlists/{id}/items with uris body."""
    mock_http = MagicMock()
    mock_http.request.return_value = _ok_response({"snapshot_id": "snap1"})

    client = _make_client(tmp_path, mock_http)
    uris = ["spotify:track:t1", "spotify:track:t2"]
    result = client.add_tracks_to_playlist("playlist123", uris)

    args, kwargs = mock_http.request.call_args
    assert args[0] == "POST"
    assert args[1] == BASE_URL + "/playlists/playlist123/items"
    assert kwargs["json"]["uris"] == uris
    assert result == {"snapshot_id": "snap1"}
