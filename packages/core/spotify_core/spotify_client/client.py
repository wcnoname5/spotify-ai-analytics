"""Typed Spotify Web API client with automatic token refresh.

All Spotify API calls must go through this module — no direct httpx/requests
calls to Spotify from other packages.
"""
import logging
from pathlib import Path
from typing import Optional, Sequence, Union

import httpx

from .errors import (
    SpotifyAuthError,
    SpotifyNoActiveDeviceError,
    SpotifyPremiumRequiredError,
)
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
            SpotifyAuthError: If no token is found for the user even after refresh.
        """
        if is_token_expired(self.db_path, self.user_id):
            logger.info("Token expired for user %s - refreshing", self.user_id)
            self._refresh_token()

        token_data = load_tokens(self.db_path, self.user_id, self.fernet_key)
        if token_data is None:
            raise SpotifyAuthError(
                f"No token found for user {self.user_id!r} - run OAuth flow first."
            )
        return token_data["access_token"]

    def _refresh_token(self) -> None:
        """Perform the token refresh POST and persist the new tokens.

        Raises:
            SpotifyAuthError: If no refresh token is stored for the user.
        """
        token_data = load_tokens(self.db_path, self.user_id, self.fernet_key)
        if token_data is None:
            raise SpotifyAuthError(
                f"Cannot refresh - no stored token for user {self.user_id!r}."
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
            SpotifyAuthError: If the request returns 401 even after a refresh retry.
            SpotifyPremiumRequiredError: If the endpoint requires Spotify Premium.
            SpotifyNoActiveDeviceError: If a playback command has no active device.
            httpx.HTTPStatusError: On other non-2xx responses.
        """
        access_token = self._get_access_token()
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {access_token}"

        url = BASE_URL + path
        response = self._client.request(method, url, headers=headers, **kwargs)

        # If 401, attempt a single refresh and retry.
        if response.status_code == 401:
            logger.warning("Received 401 - refreshing token and retrying for user %s", self.user_id)
            self._refresh_token()
            token_data = load_tokens(self.db_path, self.user_id, self.fernet_key)
            if token_data is None:
                raise SpotifyAuthError(
                    f"401 Unauthorized after refresh - token missing for user {self.user_id!r}."
                )
            headers["Authorization"] = f"Bearer {token_data['access_token']}"
            response = self._client.request(method, url, headers=headers, **kwargs)

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            try:
                body = exc.response.json()
            except Exception:
                body = exc.response.text
            status = exc.response.status_code
            logger.error(
                "_request error: %s %s status=%d body=%s",
                method, path, status, body,
            )
            reason = ""
            body_text = ""
            if isinstance(body, dict):
                inner = body.get("error") if isinstance(body.get("error"), dict) else {}
                reason = (inner.get("reason") or "").upper() if isinstance(inner, dict) else ""
                body_text = str(body).upper()
            else:
                body_text = str(body).upper()

            if status == 401:
                raise SpotifyAuthError(f"HTTP 401: {body}") from exc
            if status == 403 and "PREMIUM" in body_text:
                raise SpotifyPremiumRequiredError(f"HTTP 403: {body}") from exc
            if reason == "NO_ACTIVE_DEVICE" or "NO_ACTIVE_DEVICE" in body_text:
                raise SpotifyNoActiveDeviceError(f"HTTP {status}: {body}") from exc
            raise httpx.HTTPStatusError(
                f"HTTP {status}: {body}",
                request=exc.request,
                response=exc.response,
            ) from exc
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
        logger.debug("get_current_user")
        try:
            response = self._request("GET", "/me")
            result = response.json()
            logger.info("get_current_user success: user_id=%s", result.get("id"))
            return result
        except Exception as exc:
            logger.error("get_current_user failed: %s", exc)
            raise

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
        logger.debug("get_recently_played: limit=%d after=%s before=%s", limit, after, before)
        try:
            # TODO: the before/after logic for this api is quite weird it reuqires more tests.
            params: dict = {"limit": limit}
            if after and before:
                raise ValueError("Only one of 'after' or 'before' can be set for get_recently_played")

            if after is not None:
                params["after"] = after
            if before is not None:
                params["before"] = before

            response = self._request("GET", "/me/player/recently-played", params=params)
            result = response.json()
            logger.info("get_recently_played success: items=%d", len(result.get("items", [])))
            return result
        except Exception as exc:
            logger.error("get_recently_played failed: %s", exc)
            raise

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
        logger.debug("get_top_items: type=%s time_range=%s limit=%d", type, time_range, limit)
        try:
            params = {"time_range": time_range, "limit": limit}
            response = self._request("GET", f"/me/top/{type}", params=params)
            result = response.json()
            logger.info("get_top_items success: type=%s items=%d", type, len(result.get("items", [])))
            return result
        except Exception as exc:
            logger.error("get_top_items failed: type=%s %s", type, exc)
            raise

    # ------------------------------------------------------------------
    # Playback state
    # ------------------------------------------------------------------

    def get_currently_playing(self) -> Optional[dict]:
        """Return the user's currently playing track/episode.

        Calls ``GET /me/player/currently-playing``.

        Returns:
            Currently playing object, or ``None`` if nothing is playing.
        """
        logger.debug("get_currently_playing")
        try:
            response = self._request("GET", "/me/player/currently-playing")
            if response.status_code == 204:
                logger.info("get_currently_playing: nothing playing")
                return None
            result = response.json()
            logger.info("get_currently_playing success: is_playing=%s", result.get("is_playing"))
            return result
        except Exception as exc:
            logger.error("get_currently_playing failed: %s", exc)
            raise

    def get_devices(self) -> dict:
        """Return the user's available playback devices.

        Calls ``GET /me/player/devices``.

        Returns:
            Dict with a ``devices`` list.
        """
        logger.debug("get_devices")
        try:
            response = self._request("GET", "/me/player/devices")
            result = response.json()
            logger.info("get_devices success: count=%d", len(result.get("devices", [])))
            return result
        except Exception as exc:
            logger.error("get_devices failed: %s", exc)
            raise

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
        logger.debug("play: device_id=%r uris=%s context_uri=%r", device_id, uris, context_uri)
        try:
            params = {}
            if device_id is not None:
                params["device_id"] = device_id

            body: dict = {}
            if uris is not None:
                body["uris"] = list(uris)
            if context_uri is not None:
                body["context_uri"] = context_uri

            self._request("PUT", "/me/player/play", params=params, json=body)
            logger.info("play success: device_id=%r", device_id)
        except Exception as exc:
            logger.error("play failed: %s", exc)
            raise

    def pause(self, device_id: Optional[str] = None) -> None:
        """Pause playback.

        Calls ``PUT /me/player/pause``.

        Args:
            device_id: Optional device to target.
        """
        logger.debug("pause: device_id=%r", device_id)
        try:
            params = {}
            if device_id is not None:
                params["device_id"] = device_id
            self._request("PUT", "/me/player/pause", params=params)
            logger.info("pause success")
        except Exception as exc:
            logger.error("pause failed: %s", exc)
            raise

    def skip_to_next(self, device_id: Optional[str] = None) -> None:
        """Skip to the next track.

        Calls ``POST /me/player/next``.

        Args:
            device_id: Optional device to target.
        """
        logger.debug("skip_to_next: device_id=%r", device_id)
        try:
            params = {}
            if device_id is not None:
                params["device_id"] = device_id
            self._request("POST", "/me/player/next", params=params)
            logger.info("skip_to_next success")
        except Exception as exc:
            logger.error("skip_to_next failed: %s", exc)
            raise

    def set_volume(self, volume_percent: int, device_id: Optional[str] = None) -> None:
        """Set the playback volume.

        Calls ``PUT /me/player/volume``.

        Args:
            volume_percent: Volume level 0–100.
            device_id: Optional device to target.
        """
        logger.debug("set_volume: volume_percent=%d device_id=%r", volume_percent, device_id)
        try:
            params: dict = {"volume_percent": volume_percent}
            if device_id is not None:
                params["device_id"] = device_id
            self._request("PUT", "/me/player/volume", params=params)
            logger.info("set_volume success: volume_percent=%d", volume_percent)
        except Exception as exc:
            logger.error("set_volume failed: %s", exc)
            raise

    def add_to_queue(self, uri: str, device_id: Optional[str] = None) -> None:
        """Add a track or episode to the user's queue.

        Calls ``POST /me/player/queue``.

        Args:
            uri: Spotify URI of the item to queue.
            device_id: Optional device to target.
        """
        logger.debug("add_to_queue: uri=%r device_id=%r", uri, device_id)
        try:
            params: dict = {"uri": uri}
            if device_id is not None:
                params["device_id"] = device_id
            self._request("POST", "/me/player/queue", params=params)
            logger.info("add_to_queue success: uri=%r", uri)
        except Exception as exc:
            logger.error("add_to_queue failed: %s", exc)
            raise

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
        """Create a new playlist for the authenticated user.

        Calls ``POST /me/playlists`` (user_id kept for signature compat but not sent
        — Spotify deprecated ``POST /users/{id}/playlists`` and returns 403 for it).

        Args:
            user_id: Unused; kept for call-site compatibility.
            name: Name for the new playlist.
            public: Whether the playlist should be public.
            description: Optional description.

        Returns:
            Spotify playlist object.
        """
        logger.debug("create_playlist: name=%r public=%s", name, public)
        try:
            body = {"name": name, "public": public, "description": description}
            response = self._request("POST", "/me/playlists", json=body)
            result = response.json()
            logger.info("create_playlist success: playlist_id=%s", result.get("id"))
            return result
        except Exception as exc:
            logger.error("create_playlist failed: %s", exc)
            raise

    def add_tracks_to_playlist(self, playlist_id: str, uris: Sequence[str]) -> dict:
        """Add tracks to an existing playlist.

        Calls ``POST /playlists/{playlist_id}/items``.

        Args:
            playlist_id: Spotify playlist ID.
            uris: List of Spotify track URIs to add.

        Returns:
            Snapshot ID response dict.
        Note: endpoint ``/playlists/{playlist_id}/tracks`` is deprecated.
        """
        logger.debug("add_tracks_to_playlist: playlist_id=%s count=%d", playlist_id, len(list(uris)))
        try:
            body = {"uris": list(uris)}
            response = self._request("POST", f"/playlists/{playlist_id}/items", json=body)
            result = response.json()
            logger.info("add_tracks_to_playlist success: playlist_id=%s", playlist_id)
            return result
        except Exception as exc:
            logger.error("add_tracks_to_playlist failed: playlist_id=%s %s", playlist_id, exc)
            raise

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
        logger.debug("search: query=%r types=%s limit=%d", query, list(types), limit)
        try:
            params = {
                "q": query,
                "type": ",".join(types),
                "limit": limit,
            }
            response = self._request("GET", "/search", params=params)
            result = response.json()
            logger.info("search success: query=%r", query)
            return result
        except Exception as exc:
            logger.error("search failed: query=%r %s", query, exc)
            raise
