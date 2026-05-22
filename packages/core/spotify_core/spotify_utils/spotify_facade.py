"""Integrated Facade/Service for Spotify-related operations, DB sync and others.

These tools wrap SpotifyClient method and DB operations (e.g., ``sync_api_to_db``).
Playback control requires Spotify Premium.
For LangChain-wrapped versions see agent/playback_tools.py (AgentPlaybackTools).

Errors propagate as typed exceptions from ``spotify_core.spotify_client.errors``
(SpotifyAuthError, SpotifyPremiumRequiredError, SpotifyNoActiveDeviceError) or as
``httpx.HTTPStatusError`` for other non-2xx responses. The presentation layer
(MCP server, agent) is responsible for converting them into user-facing responses.
"""
from typing import Optional, List
from loguru import logger

from ..spotify_client.client import SpotifyClient
from ..db.pipeline import sync_api_to_db

class SpotifyToolFacade:
    """
    Integrated Facade of Spotify API services and DB sync operations.
    This class provides high-level methods that wrap SpotifyClient operations and database synchronization, making it easier to use in various contexts (e.g., agents, MCP server).
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
        """Return the currently playing track, or a status dict if nothing is playing."""
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
            Dict keyed by type, each containing a list of simplified items.
        """
        if types is None:
            types = ["track"]
        raw = self._client.search(query, types=types, limit=limit)

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
        """Return the user's available Spotify playback devices."""
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

    def play_track(self, uri: str, device_id: Optional[str] = None) -> dict:
        """Start playing a specific track by Spotify URI."""
        self._client.play(uris=[uri], device_id=device_id)
        return {"status": "playing", "uri": uri}

    def play_playlist_or_album(self, context_uri: str, device_id: Optional[str] = None) -> dict:
        """Start playing a specific album or playlist by Spotify URI.

        Args:
            context_uri: Spotify URI of the context to play. Valid contexts are
                albums, artists & playlists (e.g. ``spotify:album:<id>`` or
                ``spotify:playlist:<id>``).
            device_id: Optional Spotify device ID to target.
        """
        self._client.play(context_uri=context_uri, device_id=device_id)
        return {"status": "playing", "context_uri": context_uri}

    def pause(self) -> dict:
        """Pause the current playback."""
        self._client.pause()
        return {"status": "paused"}

    def skip(self) -> dict:
        """Skip to the next track."""
        self._client.skip_to_next()
        return {"status": "skipped"}

    def set_volume(self, volume_percent: int) -> dict:
        """Set the playback volume (clamped to 0–100)."""
        pct = max(0, min(100, volume_percent))
        self._client.set_volume(pct)
        return {"status": "volume_set", "volume_percent": pct}

    def add_to_queue(self, uri: str) -> dict:
        """Add a track to the playback queue."""
        self._client.add_to_queue(uri)
        return {"status": "queued", "uri": uri}

    # ------------------------------------------------------------------
    # Playlist management
    # ------------------------------------------------------------------

    def create_playlist(self, name: str, track_uris: List[str], description: str = "") -> dict:
        """Create a new Spotify playlist and add tracks to it."""
        # In Spotify API v1, create-playlist and add-tracks are two separate calls.
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

    # ------------------------------------------------------------------
    # History sync
    # ------------------------------------------------------------------

    def sync_recent_history(self) -> dict:
        """Fetch the 50 most recent Spotify plays and store them in the local DB."""
        return sync_api_to_db(
            db_path=self._db_path,
            tokens_db_path=self._tokens_db_path,
            user_id=self._user_id,
            client_id=self._client_id,
            fernet_key=self._fernet_key,
        )
