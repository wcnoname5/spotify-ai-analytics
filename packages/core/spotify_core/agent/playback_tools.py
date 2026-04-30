"""Playback and sync tools for the Spotify analytics agent.

These tools wrap SpotifyClient methods and are designed to be registered
as LangChain tools on the agent. Playback tools require Spotify Premium.
"""
import logging
from typing import Optional, List
from langchain_core.tools import tool

from ..spotify_client.client import SpotifyClient
from ..db.pipeline import sync_api_to_db

logger = logging.getLogger(__name__)

_PREMIUM_REQUIRED = {"error": "Spotify Premium required for playback control."}


class SpotifyPlaybackTools:
    """Tools for playback control, queue management, and history sync."""

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
            ]

        if "albums" in raw:
            result["albums"] = [
                {
                    "name": a.get("name"),
                    "artist": (a.get("artists") or [{}])[0].get("name"),
                    "uri": a.get("uri"),
                }
                for a in raw["albums"].get("items", [])
            ]

        if "artists" in raw:
            result["artists"] = [
                {"name": a.get("name"), "uri": a.get("uri")}
                for a in raw["artists"].get("items", [])
            ]

        if "playlists" in raw:
            result["playlists"] = [
                {
                    "name": p.get("name"),
                    "owner": (p.get("owner") or {}).get("display_name"),
                    "uri": p.get("uri"),
                }
                for p in raw["playlists"].get("items", [])
            ]

        return result

    # ------------------------------------------------------------------
    # Playback control (Premium required)
    # ------------------------------------------------------------------

    def play_track(self, uri: str) -> dict:
        """Start playing a specific track by Spotify URI.

        Args:
            uri: Spotify track URI (e.g. "spotify:track:4iV5W9uYEdYUVa79Axb7Rh").

        Returns:
            {"status": "playing", "uri": uri} or {"error": ...}.
        """
        try:
            self._client.play(uris=[uri])
            return {"status": "playing", "uri": uri}
        except Exception as exc:
            logger.error("play_track failed: %s", exc)
            if "403" in str(exc) or "PREMIUM" in str(exc).upper():
                return _PREMIUM_REQUIRED
            return {"error": str(exc)}

    def play_playlist_or_album(self, context_uri: str) -> dict:
        """Start playing a specific album or playlist by Spotify URI.

        Args:
            context_uri: Spotify URI of the context to play. Valid contexts are albums, artists & playlists. (e.g. "spotify:album:<id>" or "spotify:playlist:<id>").

        Returns:
            {"status": "playing", "context_uri": context_uri} or {"error": ...}.
        """
        try:
            self._client.play(context_uri=context_uri)
            return {"status": "playing", "context_uri": context_uri}
        except Exception as exc:
            logger.error("play_playlist_or_album failed: %s", exc)
            if "403" in str(exc) or "PREMIUM" in str(exc).upper():
                return _PREMIUM_REQUIRED
            return {"error": str(exc)}

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

    # ------------------------------------------------------------------
    # Tool registration
    # ------------------------------------------------------------------

    def get_tools(self) -> list:
        """Return all playback/sync tools as LangChain tools."""
        return [
            tool(self.get_now_playing),
            tool(self.play_track),
            tool(self.pause),
            tool(self.skip),
            tool(self.set_volume),
            tool(self.add_to_queue),
            tool(self.create_playlist),
            tool(self.sync_recent_history),
        ]
