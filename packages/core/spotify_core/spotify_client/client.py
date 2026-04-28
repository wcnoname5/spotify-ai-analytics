"""Typed Spotify Web API client with automatic token refresh.

All Spotify API calls must go through this module — no direct httpx/requests
calls to Spotify from other packages.
"""
import logging
from pathlib import Path
from typing import Optional, Sequence, Union

import httpx

from .token_store import load_tokens, save_tokens, is_token_expired

logger = logging.getLogger(__name__)

BASE_URL = "https://api.spotify.com/v1"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"


class SpotifyClient:
    """Authenticated Spotify API client with automatic token refresh.

    Args:
        db_path: Path to the SQLite database containing encrypted tokens.
        user_id: Spotify user ID whose tokens will be loaded.
        client_id: Spotify app client ID (needed for token refresh).
        fernet_key: Raw Fernet key bytes used to decrypt stored tokens.
        http_client: Optional ``httpx.Client`` for dependency injection in
            tests. If ``None``, a new client is created on first use.
    """

    def __init__(
        self,
        db_path: Union[str, Path],
        user_id: str,
        client_id: str,
        fernet_key: bytes,
        http_client: Optional[httpx.Client] = None,
    ) -> None:
        self.db_path = db_path
        self.user_id = user_id
        self.client_id = client_id
        self.fernet_key = fernet_key
        self._http_client = http_client
        self._owns_client = http_client is None

    @property
    def _client(self) -> httpx.Client:
        if self._http_client is None:
            self._http_client = httpx.Client()
        return self._http_client

    def close(self) -> None:
        """Close the underlying HTTP client if it was created internally."""
        if self._owns_client and self._http_client is not None:
            self._http_client.close()
            self._http_client = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    # ------------------------------------------------------------------
    # Token management
    # ------------------------------------------------------------------

    def _get_access_token(self) -> str:
        """Load token from store, refresh if expired, return access_token string.

        Raises:
            RuntimeError: If no token is found for the user even after refresh.
        """
        if is_token_expired(self.db_path, self.user_id):
            logger.info("Token expired for user %s — refreshing", self.user_id)
            self._refresh_token()

        token_data = load_tokens(self.db_path, self.user_id, self.fernet_key)
        if token_data is None:
            raise RuntimeError(
                f"No token found for user {self.user_id!r} — run OAuth flow first."
            )
        return token_data["access_token"]

    def _refresh_token(self) -> None:
        """Perform the token refresh POST and persist the new tokens."""
        token_data = load_tokens(self.db_path, self.user_id, self.fernet_key)
        if token_data is None:
            raise RuntimeError(
                f"Cannot refresh — no stored token for user {self.user_id!r}."
            )

        refresh_token = token_data["refresh_token"]
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self.client_id,
        }
        response = self._client.post(
            SPOTIFY_TOKEN_URL,
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response.raise_for_status()
        new_token = response.json()

        # Spotify may omit refresh_token in the response — keep the old one.
        if "refresh_token" not in new_token:
            new_token["refresh_token"] = refresh_token

        save_tokens(self.db_path, self.user_id, new_token, self.fernet_key)
        logger.info("Token refreshed and saved for user %s", self.user_id)

    # ------------------------------------------------------------------
    # Core request helper
    # ------------------------------------------------------------------

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        """Make an authenticated request with automatic 401 retry after refresh.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE, …).
            path: URL path relative to ``BASE_URL`` (must start with ``/``).
            **kwargs: Passed directly to ``httpx.Client.request``.

        Returns:
            The ``httpx.Response`` object.

        Raises:
            httpx.HTTPStatusError: On non-2xx responses after retry.
        """
        access_token = self._get_access_token()
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {access_token}"

        url = BASE_URL + path
        response = self._client.request(method, url, headers=headers, **kwargs)

        # If 401, attempt a single refresh and retry.
        if response.status_code == 401:
            logger.warning("Received 401 — refreshing token and retrying for user %s", self.user_id)
            self._refresh_token()
            token_data = load_tokens(self.db_path, self.user_id, self.fernet_key)
            if token_data is None:
                response.raise_for_status()
                return response
            headers["Authorization"] = f"Bearer {token_data['access_token']}"
            response = self._client.request(method, url, headers=headers, **kwargs)

        response.raise_for_status()
        return response

    # ------------------------------------------------------------------
    # User / profile endpoints
    # ------------------------------------------------------------------

    def get_current_user(self) -> dict:
        """Return the current user's Spotify profile.

        Calls ``GET /me``.

        Returns:
            Spotify user profile object as a dict.
        """
        response = self._request("GET", "/me")
        return response.json()

    # ------------------------------------------------------------------
    # Listening history & top items
    # ------------------------------------------------------------------

    def get_recently_played(
        self,
        limit: int = 50,
        after: Optional[int] = None,
        before: Optional[int] = None,
    ) -> dict:
        """Return the user's recently played tracks.

        Calls ``GET /me/player/recently-played``.

        Args:
            limit: Number of items to return (max 50).
            after: Unix timestamp in ms — return only items played after this cursor.
            before: Unix timestamp in ms — return only items played before this cursor.

        Only one of ``after`` / ``before`` should be set per call.

        Returns:
            Spotify paging object containing track items.
        """
        # TODO: the before/after logic for this api is quite weird it reuqires more tests.
        params: dict = {"limit": limit}
        if after and before:
            raise ValueError("Only one of 'after' or 'before' can be set for get_recently_played")
        
        if after is not None:
            params["after"] = after
        if before is not None:
            params["before"] = before

        response = self._request("GET", "/me/player/recently-played", params=params)
        return response.json()

    def get_top_items(
        self,
        type: str,
        time_range: str = "medium_term",
        limit: int = 20,
    ) -> dict:
        """Return the user's top artists or tracks.

        Calls ``GET /me/top/{type}``.

        Args:
            type: ``"artists"`` or ``"tracks"``.
            time_range: ``"short_term"`` (4 weeks), ``"medium_term"`` (6 months),
                or ``"long_term"`` (all time).
            limit: Number of items to return (max 50).

        Returns:
            Spotify paging object containing top items.
        """
        params = {"time_range": time_range, "limit": limit}
        response = self._request("GET", f"/me/top/{type}", params=params)
        return response.json()

    # ------------------------------------------------------------------
    # Playback state
    # ------------------------------------------------------------------

    def get_currently_playing(self) -> Optional[dict]:
        """Return the user's currently playing track/episode.

        Calls ``GET /me/player/currently-playing``.

        Returns:
            Currently playing object, or ``None`` if nothing is playing.
        """
        response = self._request("GET", "/me/player/currently-playing")
        if response.status_code == 204:
            return None
        return response.json()

    def get_devices(self) -> dict:
        """Return the user's available playback devices.

        Calls ``GET /me/player/devices``.

        Returns:
            Dict with a ``devices`` list.
        """
        response = self._request("GET", "/me/player/devices")
        return response.json()

    # ------------------------------------------------------------------
    # Playback control
    # ------------------------------------------------------------------

    def play(
        self,
        device_id: Optional[str] = None,
        uris: Optional[Sequence[str]] = None,
        context_uri: Optional[str] = None,
    ) -> None:
        """Start or resume playback.

        Calls ``PUT /me/player/play``.

        Args:
            device_id: Optional device to target.
            uris: Optional list of Spotify track URIs to play.
            context_uri: Optional context URI (album, artist, playlist) to play.
        """
        params = {}
        if device_id is not None:
            params["device_id"] = device_id

        body: dict = {}
        if uris is not None:
            body["uris"] = list(uris)
        if context_uri is not None:
            body["context_uri"] = context_uri

        self._request("PUT", "/me/player/play", params=params, json=body)

    def pause(self, device_id: Optional[str] = None) -> None:
        """Pause playback.

        Calls ``PUT /me/player/pause``.

        Args:
            device_id: Optional device to target.
        """
        params = {}
        if device_id is not None:
            params["device_id"] = device_id
        self._request("PUT", "/me/player/pause", params=params)

    def skip_to_next(self, device_id: Optional[str] = None) -> None:
        """Skip to the next track.

        Calls ``POST /me/player/next``.

        Args:
            device_id: Optional device to target.
        """
        params = {}
        if device_id is not None:
            params["device_id"] = device_id
        self._request("POST", "/me/player/next", params=params)

    def set_volume(self, volume_percent: int, device_id: Optional[str] = None) -> None:
        """Set the playback volume.

        Calls ``PUT /me/player/volume``.

        Args:
            volume_percent: Volume level 0–100.
            device_id: Optional device to target.
        """
        params: dict = {"volume_percent": volume_percent}
        if device_id is not None:
            params["device_id"] = device_id
        self._request("PUT", "/me/player/volume", params=params)

    def add_to_queue(self, uri: str, device_id: Optional[str] = None) -> None:
        """Add a track or episode to the user's queue.

        Calls ``POST /me/player/queue``.

        Args:
            uri: Spotify URI of the item to queue.
            device_id: Optional device to target.
        """
        params: dict = {"uri": uri}
        if device_id is not None:
            params["device_id"] = device_id
        self._request("POST", "/me/player/queue", params=params)

    # ------------------------------------------------------------------
    # Playlist management
    # ------------------------------------------------------------------

    def create_playlist(
        self,
        user_id: str,
        name: str,
        public: bool = False,
        description: str = "",
    ) -> dict:
        """Create a new playlist for a Spotify user.

        Calls ``POST /users/{user_id}/playlists``.

        Args:
            user_id: Spotify user ID who will own the playlist.
            name: Name for the new playlist.
            public: Whether the playlist should be public.
            description: Optional description.

        Returns:
            Spotify playlist object.
        """
        body = {"name": name, "public": public, "description": description}
        response = self._request("POST", f"/users/{user_id}/playlists", json=body)
        return response.json()

    def add_tracks_to_playlist(self, playlist_id: str, uris: Sequence[str]) -> dict:
        """Add tracks to an existing playlist.

        Calls ``POST /playlists/{playlist_id}/tracks``.

        Args:
            playlist_id: Spotify playlist ID.
            uris: List of Spotify track URIs to add.

        Returns:
            Snapshot ID response dict.
        """
        body = {"uris": list(uris)}
        response = self._request("POST", f"/playlists/{playlist_id}/tracks", json=body)
        return response.json()

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        types: Sequence[str] = ("track",),
        limit: int = 20,
    ) -> dict:
        """Search the Spotify catalogue.

        Calls ``GET /search``.

        Args:
            query: Search query string.
            types: Sequence of item types to search for, e.g. ``("track",
                "artist")``.
            limit: Number of results per type (max 50).

        Returns:
            Spotify search results object.
        """
        params = {
            "q": query,
            "type": ",".join(types),
            "limit": limit,
        }
        response = self._request("GET", "/search", params=params)
        return response.json()
