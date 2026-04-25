"""Tests for Spotify OAuth PKCE auth flow."""
import pytest
from unittest.mock import patch, MagicMock
import httpx


@pytest.mark.unit
def test_build_auth_url_contains_required_params():
    """build_auth_url includes all required PKCE parameters."""
    from spotify_core.spotify_client.auth import build_auth_url
    url = build_auth_url(
        client_id="test_client",
        redirect_uri="http://127.0.0.1:8888/callback",
        code_challenge="abc123",
        state="xyz",
    )
    assert "client_id=test_client" in url
    assert "code_challenge_method=S256" in url
    assert "code_challenge=abc123" in url
    assert "response_type=code" in url
    assert "state=xyz" in url
    assert url.startswith("https://accounts.spotify.com/authorize")


@pytest.mark.unit
def test_build_auth_url_uses_127_not_localhost():
    """build_auth_url does not contain localhost (Spotify banned it Nov 2025)."""
    from spotify_core.spotify_client.auth import build_auth_url
    url = build_auth_url("cid", "http://127.0.0.1:8888/callback", "ch", "st")
    assert "localhost" not in url


@pytest.mark.unit
def test_build_auth_url_encodes_scopes():
    """build_auth_url encodes space-separated scopes correctly."""
    from spotify_core.spotify_client.auth import build_auth_url
    url = build_auth_url("cid", "http://127.0.0.1:8888/callback", "ch", "st",
                          scopes="user-read-recently-played user-top-read")
    assert "user-read-recently-played" in url
    assert "user-top-read" in url


@pytest.mark.unit
def test_exchange_code_uses_correct_payload():
    """exchange_code_for_tokens sends correct POST body to Spotify token endpoint."""
    from spotify_core.spotify_client.auth import exchange_code_for_tokens

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "access_token": "at", "refresh_token": "rt", "expires_in": 3600
    }
    mock_response.raise_for_status = MagicMock()

    mock_client = MagicMock()
    mock_client.post.return_value = mock_response

    result = exchange_code_for_tokens(
        code="auth_code",
        code_verifier="verifier",
        client_id="my_client",
        redirect_uri="http://127.0.0.1:8888/callback",
        http_client=mock_client,
    )

    assert result["access_token"] == "at"
    call_args = mock_client.post.call_args
    posted_data = call_args[1].get("data")
    assert posted_data["grant_type"] == "authorization_code"
    assert posted_data["code"] == "auth_code"
    assert posted_data["code_verifier"] == "verifier"
    assert posted_data["client_id"] == "my_client"
    assert posted_data["redirect_uri"] == "http://127.0.0.1:8888/callback"


@pytest.mark.unit
def test_exchange_code_raises_on_http_error():
    """exchange_code_for_tokens raises HTTPStatusError on non-2xx response."""
    from spotify_core.spotify_client.auth import exchange_code_for_tokens

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "400", request=MagicMock(), response=MagicMock()
    )
    mock_client.post.return_value = mock_response

    with pytest.raises(httpx.HTTPStatusError):
        exchange_code_for_tokens("code", "verifier", "cid", "http://127.0.0.1:8888/callback", mock_client)


@pytest.mark.unit
def test_default_scopes_include_key_permissions():
    """DEFAULT_SCOPES includes all required Spotify permissions."""
    from spotify_core.spotify_client.auth import DEFAULT_SCOPES
    required = [
        "user-read-recently-played",
        "user-top-read",
        "user-read-playback-state",
        "user-modify-playback-state",
        "user-read-currently-playing",
        "playlist-modify-public",
        "playlist-modify-private",
    ]
    for scope in required:
        assert scope in DEFAULT_SCOPES


@pytest.mark.unit
def test_exchange_code_closes_own_client():
    """exchange_code_for_tokens creates and closes its own httpx.Client when not provided."""
    from spotify_core.spotify_client.auth import exchange_code_for_tokens
    from unittest.mock import patch, call

    with patch("spotify_core.spotify_client.auth.httpx.Client") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "access_token": "at", "refresh_token": "rt", "expires_in": 3600
        }
        mock_response.raise_for_status = MagicMock()
        mock_client.post.return_value = mock_response

        result = exchange_code_for_tokens(
            code="auth_code",
            code_verifier="verifier",
            client_id="my_client",
            redirect_uri="http://127.0.0.1:8888/callback",
        )

        mock_client_class.assert_called_once()
        mock_client.close.assert_called_once()
        assert result["access_token"] == "at"


def _pkce_server_class(callback_params: dict):
    """Factory: returns a fake HTTPServer class that populates run_pkce_flow's inner result dict."""

    class _FakeHTTPServer:
        timeout = 120

        def __init__(self, addr, handler_class):
            self._handler_class = handler_class

        def handle_request(self):
            # do_GET captures `result` as its only closure variable; write into it directly.
            result_dict = self._handler_class.do_GET.__closure__[0].cell_contents
            result_dict.update(callback_params)

        def server_close(self):
            pass

    return _FakeHTTPServer


@pytest.mark.unit
def test_run_pkce_flow_raises_on_state_mismatch():
    """run_pkce_flow raises RuntimeError when the callback state doesn't match."""
    from spotify_core.spotify_client.auth import run_pkce_flow

    fake_server = _pkce_server_class({"code": "auth_code", "state": "WRONG_STATE"})
    with patch("spotify_core.spotify_client.auth.http.server.HTTPServer", fake_server), \
         patch("spotify_core.spotify_client.auth.webbrowser.open"):
        with pytest.raises(RuntimeError, match="State mismatch"):
            run_pkce_flow("client_id", port=9999)


@pytest.mark.unit
def test_run_pkce_flow_raises_on_missing_code():
    """run_pkce_flow raises RuntimeError when callback has no authorization code."""
    from spotify_core.spotify_client.auth import run_pkce_flow

    # Patch token_urlsafe so the fixed state in callback_params matches the generated state.
    fake_server = _pkce_server_class({"state": "fixed_state"})
    with patch("spotify_core.spotify_client.auth.http.server.HTTPServer", fake_server), \
         patch("spotify_core.spotify_client.auth.webbrowser.open"), \
         patch("secrets.token_urlsafe", return_value="fixed_state"):
        with pytest.raises(RuntimeError, match="no authorization code"):
            run_pkce_flow("client_id", port=9998)


@pytest.mark.unit
def test_run_pkce_flow_raises_on_timeout():
    """run_pkce_flow raises RuntimeError when the callback server times out (no result)."""
    from spotify_core.spotify_client.auth import run_pkce_flow

    fake_server = _pkce_server_class({})  # empty dict → triggers timeout guard
    with patch("spotify_core.spotify_client.auth.http.server.HTTPServer", fake_server), \
         patch("spotify_core.spotify_client.auth.webbrowser.open"):
        with pytest.raises(RuntimeError, match="timed out"):
            run_pkce_flow("client_id", port=9997)
