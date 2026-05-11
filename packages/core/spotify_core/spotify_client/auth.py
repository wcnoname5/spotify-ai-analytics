"""Spotify OAuth 2.0 Authorization Code with PKCE flow.

Redirect URI: always http://127.0.0.1:{port}/callback
              (Spotify banned localhost as of Nov 2025)
"""
import logging
import webbrowser
import urllib.parse
import http.server
from typing import Optional
import httpx

from .pkce import generate_code_verifier, generate_code_challenge

logger = logging.getLogger(__name__)

SPOTIFY_AUTH_URL = "https://accounts.spotify.com/authorize"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"

DEFAULT_SCOPES = " ".join([
    "user-read-recently-played",
    "user-top-read",
    "user-read-playback-state",
    "user-modify-playback-state",
    "user-read-currently-playing",
    "playlist-modify-public",
    "playlist-modify-private",
])


def build_auth_url(
    client_id: str,
    redirect_uri: str,
    code_challenge: str,
    state: str,
    scopes: str = DEFAULT_SCOPES,
) -> str:
    """Build the Spotify authorization URL with PKCE parameters.

    Args:
        client_id: Spotify app client ID.
        redirect_uri: OAuth callback URI (use http://127.0.0.1:{port}/callback).
        code_challenge: S256 code challenge derived from code_verifier.
        state: CSRF protection token.
        scopes: Space-separated Spotify scopes.

    Returns:
        Full Spotify authorization URL.
    """
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "code_challenge_method": "S256",
        "code_challenge": code_challenge,
        "state": state,
        "scope": scopes,
    }
    return SPOTIFY_AUTH_URL + "?" + urllib.parse.urlencode(params)


def exchange_code_for_tokens(
    code: str,
    code_verifier: str,
    client_id: str,
    redirect_uri: str,
    http_client: Optional[httpx.Client] = None,
) -> dict:
    """Exchange an authorization code for access + refresh tokens.

    Args:
        code: Authorization code from Spotify callback.
        code_verifier: Original PKCE verifier used to generate the challenge.
        client_id: Spotify app client ID.
        redirect_uri: Must match the redirect URI used in build_auth_url.
        http_client: Optional httpx.Client for testing. If None, creates one.

    Returns:
        Token response dict with keys: access_token, refresh_token, expires_in, scope, token_type.

    Raises:
        httpx.HTTPStatusError: If Spotify returns a non-2xx response.
    """
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "code_verifier": code_verifier,
    }
    own_client = http_client is None
    client = http_client or httpx.Client()
    try:
        response = client.post(
            SPOTIFY_TOKEN_URL,
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response.raise_for_status()
        return response.json()
    finally:
        if own_client:
            client.close()


def run_pkce_flow(
    client_id: str,
    port: int = 8888,
    scopes: str = DEFAULT_SCOPES,
    open_browser: bool = True,
) -> dict:
    """Run the full PKCE authorization flow.

    Opens the browser, waits for the OAuth callback on 127.0.0.1:{port}/callback,
    then exchanges the code for tokens.

    Args:
        client_id: Spotify app client ID.
        port: Local port for the callback server. Default 8888.
        scopes: Space-separated Spotify scopes.
        open_browser: If False, just prints the URL (useful for headless environments).

    Returns:
        Token dict from Spotify.

    Raises:
        RuntimeError: If the callback returns an error parameter, state mismatch is detected, no code is received, or the 120-second timeout expires.
        httpx.HTTPStatusError: If token exchange fails.
    """
    import secrets as _secrets

    redirect_uri = f"http://127.0.0.1:{port}/callback"
    state = _secrets.token_urlsafe(16)
    code_verifier = generate_code_verifier()
    code_challenge = generate_code_challenge(code_verifier)

    auth_url = build_auth_url(client_id, redirect_uri, code_challenge, state, scopes)

    # Shared result container for the handler thread
    result: dict = {}

    class _CallbackHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            params = dict(urllib.parse.parse_qsl(parsed.query))
            result.update(params)
            # Send a simple success page
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h1>Authentication complete. You can close this tab.</h1>")

        def log_message(self, format, *args):
            pass  # suppress default request logging

    server = http.server.HTTPServer(("127.0.0.1", port), _CallbackHandler)
    server.timeout = 120  # 2-minute wait for user to authorize

    if open_browser:
        webbrowser.open(auth_url)
    else:
        logger.info(f"Open this URL to authenticate:\n{auth_url}")

    logger.info(f"Waiting for OAuth callback on http://127.0.0.1:{port}/callback ...")
    server.handle_request()  # blocks until one request is received or timeout
    server.server_close()

    if not result:
        raise RuntimeError("OAuth flow timed out - no callback received within 120 seconds.")
    if "error" in result:
        raise RuntimeError(f"OAuth error: {result['error']}")
    if result.get("state") != state:
        raise RuntimeError(f"State mismatch - possible CSRF. Expected {state!r}, got {result.get('state')!r}")
    if "code" not in result:
        raise RuntimeError("OAuth callback contained no authorization code.")

    code = result["code"]
    return exchange_code_for_tokens(code, code_verifier, client_id, redirect_uri)
