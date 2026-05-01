"""Playback and sync tools — no LangChain dependency.

These tools wrap SpotifyClient methods. Playback control requires Spotify Premium.
For LangChain-wrapped versions see agent/playback_tools.py (AgentPlaybackTools).
"""
import logging
from typing import Optional, List

from ..spotify_client.client import SpotifyClient
from ..db.pipeline import sync_api_to_db

logger = logging.getLogger(__name__)

_PREMIUM_REQUIRED = {"error": "Spotify Premium required for playback control."}


class SpotifyPlaybackTools:
    """
    Tools for playback control, queue management, and history sync.
    
    Note: At this stages the methods returns a dict: {error: ...} on failure, which the MCP server layer can enrich with auth hints if needed.
    In the future we may want to raise custom exceptions here and handle them in the server layer instead.
    """

    def __init__(
        self,
        client: SpotifyClient,
        db_path: str,
        tokens_db_path: str,
        user_id: str,
        client_id: str,
        fernet_key: bytes,
    ) -> None:
        self._client = client
        self._db_path = db_path
        self._tokens_db_path = tokens_db_path
        self._user_id = user_id
        self._client_id = client_id
        self._fernet_key = fernet_key

    # ------------------------------------------------------------------
    # Playback state
    # ------------------------------------------------------------------

    def get_now_playing(self) -> dict:
        """Return the currently playing track, or a message if nothing is playing.

        Returns:
            Dict with track info, or {"status": "nothing_playing"}.
        """
        try:
            result = self._client.get_currently_playing()
            if result is None:
                return {"status": "nothing_playing"}
            item = result.get("item") or {}
            artists = item.get("artists") or []
            return {
                "track": item.get("name"),
                "artist": artists[0]["name"] if artists else None,
                "album": (item.get("album") or {}).get("name"),
                "uri": item.get("uri"),
                "progress_ms": result.get("progress_ms"),
                "is_playing": result.get("is_playing"),
            }
        except Exception as exc:
            logger.error("get_now_playing failed: %s", exc)
            return {"error": str(exc)}
    # ------------------------------------------------------------------
    # Search and lookup tools
    # ------------------------------------------------------------------

    def search_item(
        self,
        query: str,
        types: list | None = None,
        limit: int = 5,
    ) -> dict:
        """Search the Spotify catalogue for tracks, albums, artists, or playlists.

        Args:
            query: Search query string.
            types: List of item types to search. Defaults to ["track"].
                   Valid values: "track", "album", "artist", "playlist".
            limit: Max results per type (1–50).
        Note:
            You can narrow down your search using field filters. The available filters are album, artist, track, year, upc, tag:hipster, tag:new, isrc, and genre. Each field filter only applies to certain result types.

            The artist and year filters can be used while searching albums, artists and tracks. You can filter on a single year or a range (e.g. 1955-1960).
            The album filter can be used while searching albums and tracks.
            The genre filter can be used while searching artists and tracks.
            The isrc and track filters can be used while searching tracks.
            The upc, tag:new and tag:hipster filters can only be used while searching albums. The tag:new filter will return albums released in the past two weeks and tag:hipster can be used to return only albums with the lowest 10% popularity.

            Example: q=remaster%2520track%3ADoxy%2520artist%3AMiles%2520Davis
            
        Returns:
            Dict keyed by type, each containing a list of simplified items,
            or {"error": ...} on failure.
        """
        if types is None:
            types = ["track"]
        try:
            raw = self._client.search(query, types=types, limit=limit)
        except Exception as exc:
            logger.error("search_item failed: %s", exc)
            return {"error": str(exc)}

        result: dict = {}

        if "tracks" in raw:
            result["tracks"] = [
                {
                    "name": t.get("name"),
                    "artist": (t.get("artists") or [{}])[0].get("name"),
                    "album": (t.get("album") or {}).get("name"),
                    "uri": t.get("uri"),
                }
                for t in raw["tracks"].get("items", [])
                if t is not None
            ]

        if "albums" in raw:
            result["albums"] = [
                {
                    "name": a.get("name"),
                    "artist": (a.get("artists") or [{}])[0].get("name"),
                    "uri": a.get("uri"),
                }
                for a in raw["albums"].get("items", [])
                if a is not None
            ]

        if "artists" in raw:
            result["artists"] = [
                {"name": a.get("name"), "uri": a.get("uri")}
                for a in raw["artists"].get("items", [])
                if a is not None
            ]

        if "playlists" in raw:
            result["playlists"] = [
                {
                    "name": p.get("name"),
                    "owner": (p.get("owner") or {}).get("display_name"),
                    "uri": p.get("uri"),
                }
                for p in raw["playlists"].get("items", [])
                if p is not None
            ]

        return result

    # ------------------------------------------------------------------
    # Playback control (Premium required)
    # ------------------------------------------------------------------

    def get_devices(self) -> dict:
        """Return the user's available Spotify playback devices.

        Returns:
            {"devices": [...]} where each device has id, name, type, is_active,
            volume_percent. Returns {"error": ...} on failure.
        """
        try:
            raw = self._client.get_devices()
            return {
                "devices": [
                    {
                        "id": d.get("id"),
                        "name": d.get("name"),
                        "type": d.get("type"),
                        "is_active": d.get("is_active"),
                        "volume_percent": d.get("volume_percent"),
                    }
                    for d in raw.get("devices", [])
                ]
            }
        except Exception as exc:
            logger.error("get_devices failed: %s", exc)
            return {"error": str(exc)}

    def play_track(self, uri: str, device_id: Optional[str] = None) -> dict:
        """Start playing a specific track by Spotify URI.

        Args:
            uri: Spotify track URI (e.g. "spotify:track:4iV5W9uYEdYUVa79Axb7Rh").
            device_id: Optional Spotify device ID to target. If omitted, playback
                starts on the currently active device.

        Returns:
            {"status": "playing", "uri": uri} or {"error": ...}.
        """
        try:
            self._client.play(uris=[uri], device_id=device_id)
            return {"status": "playing", "uri": uri}
        except Exception as exc:
            logger.error("play_track failed: %s", exc)
            if "403" in str(exc) or "PREMIUM" in str(exc).upper():
                return _PREMIUM_REQUIRED
            if "NO_ACTIVE_DEVICE" in str(exc):
                return self._no_active_device_error()
            return {"error": str(exc)}

    def play_playlist_or_album(self, context_uri: str, device_id: Optional[str] = None) -> dict:
        """Start playing a specific album or playlist by Spotify URI.

        Args:
            context_uri: Spotify URI of the context to play. Valid contexts are albums, artists & playlists. (e.g. "spotify:album:<id>" or "spotify:playlist:<id>").
            device_id: Optional Spotify device ID to target. If omitted, playback
                starts on the currently active device.

        Returns:
            {"status": "playing", "context_uri": context_uri} or {"error": ...}.
        """
        try:
            self._client.play(context_uri=context_uri, device_id=device_id)
            return {"status": "playing", "context_uri": context_uri}
        except Exception as exc:
            logger.error("play_playlist_or_album failed: %s", exc)
            if "403" in str(exc) or "PREMIUM" in str(exc).upper():
                return _PREMIUM_REQUIRED
            if "NO_ACTIVE_DEVICE" in str(exc):
                return self._no_active_device_error()
            return {"error": str(exc)}

    def _no_active_device_error(self) -> dict:
        """Return an enriched error dict when no active device is found."""
        devices = self.get_devices()
        return {
            "error": "No active Spotify device found. Open Spotify on a device first.",
            "available_devices": devices.get("devices", []),
            "hint": "Pass a device_id from available_devices to target a specific device.",
        }

    def pause(self) -> dict:
        """Pause the current playback.

        Returns:
            {"status": "paused"} or {"error": ...}.
        """
        try:
            self._client.pause()
            return {"status": "paused"}
        except Exception as exc:
            logger.error("pause failed: %s", exc)
            if "403" in str(exc) or "PREMIUM" in str(exc).upper():
                return _PREMIUM_REQUIRED
            return {"error": str(exc)}

    def skip(self) -> dict:
        """Skip to the next track.

        Returns:
            {"status": "skipped"} or {"error": ...}.
        """
        try:
            self._client.skip_to_next()
            return {"status": "skipped"}
        except Exception as exc:
            logger.error("skip failed: %s", exc)
            if "403" in str(exc) or "PREMIUM" in str(exc).upper():
                return _PREMIUM_REQUIRED
            return {"error": str(exc)}

    def set_volume(self, volume_percent: int) -> dict:
        """Set the playback volume.

        Args:
            volume_percent: Volume 0–100.

        Returns:
            {"status": "volume_set", "volume_percent": int} or {"error": ...}.
        """
        pct = max(0, min(100, volume_percent))
        try:
            self._client.set_volume(pct)
            return {"status": "volume_set", "volume_percent": pct}
        except Exception as exc:
            logger.error("set_volume failed: %s", exc)
            if "403" in str(exc) or "PREMIUM" in str(exc).upper():
                return _PREMIUM_REQUIRED
            return {"error": str(exc)}

    def add_to_queue(self, uri: str) -> dict:
        """Add a track to the playback queue.

        Args:
            uri: Spotify track URI.

        Returns:
            {"status": "queued", "uri": uri} or {"error": ...}.
        """
        try:
            self._client.add_to_queue(uri)
            return {"status": "queued", "uri": uri}
        except Exception as exc:
            logger.error("add_to_queue failed: %s", exc)
            if "403" in str(exc) or "PREMIUM" in str(exc).upper():
                return _PREMIUM_REQUIRED
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # Playlist management
    # ------------------------------------------------------------------

    def create_playlist(self, name: str, track_uris: List[str], description: str = "") -> dict:
        """Create a new Spotify playlist and add tracks to it.

        Args:
            name: Playlist name.
            track_uris: List of Spotify track URIs to add.
            description: Optional playlist description.

        Returns:
            {"playlist_id": str, "url": str, "track_count": int} or {"error": ...}.
        """
        try:
            # In spotify API v1, create playlist and add tracks are two separate calls.
            playlist = self._client.create_playlist(
                self._user_id, name, public=False, description=description
            )
            playlist_id = playlist["id"]
            if track_uris:
                self._client.add_tracks_to_playlist(playlist_id, track_uris)
            return {
                "playlist_id": playlist_id,
                "url": playlist.get("external_urls", {}).get("spotify", ""),
                "track_count": len(track_uris),
            }
        except Exception as exc:
            logger.error("create_playlist failed: %s", exc)
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # History sync
    # ------------------------------------------------------------------

    def sync_recent_history(self) -> dict:
        """Fetch the 50 most recent Spotify plays and store them in the local DB.

        Returns:
            {"inserted": int, "cursor_ms": int} or {"error": ...}.
        """
        try:
            return sync_api_to_db(
                db_path=self._db_path,
                tokens_db_path=self._tokens_db_path,
                user_id=self._user_id,
                client_id=self._client_id,
                fernet_key=self._fernet_key,
            )
        except Exception as exc:
            logger.error("sync_recent_history failed: %s", exc)
            return {"error": str(exc)}

