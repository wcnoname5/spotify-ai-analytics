"""MCP tools that talk to the live Spotify Web API (playback + playlists)."""
import logging
from typing import Annotated, List, Optional

from pydantic import Field
from mcp.server.fastmcp import FastMCP

from spotify_mcp.utils import enrich_auth_error
from spotify_mcp.config import (
    DB_PATH,
    DEFAULT_USER_ID,
    TOKENS_DB,
    get_client_id,
    get_fernet_key,
    make_client,
)

logger = logging.getLogger(__name__)


def _make_tools(client, user_id: str):
    '''
    Factory for `SpotifyPlaybackTools` instance to avoid circular imports. Passes through the shared client and config.
    '''
    from spotify_core.spotify_utils.playback import SpotifyPlaybackTools
    return SpotifyPlaybackTools(client, DB_PATH, TOKENS_DB, user_id, get_client_id(), get_fernet_key())


def register(mcp: FastMCP) -> None:
    """Attach Spotify Web API tools to the given FastMCP server."""

    @mcp.tool(
        name="get_now_playing",
        annotations={
            "title": "Get Currently Playing Track",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    def get_now_playing(
        user_id: Annotated[str, Field(description="Spotify user ID. Defaults to SPOTIFY_USER_ID env var.")] = DEFAULT_USER_ID,
    ) -> dict:
        """Return the currently playing Spotify track.

        Requires Spotify OAuth tokens. Returns nothing_playing if no track is active.
        """
        logger.debug("[Tool] get_now_playing: user_id=%s", user_id)
        try:
            with make_client(user_id) as client:
                result = _make_tools(client, user_id).get_now_playing()
            logger.info("[Tool] get_now_playing success: user_id=%s", user_id)
            return result
        except Exception as exc:
            logger.error("[Tool] get_now_playing failed: %s", exc)
            return enrich_auth_error({"error": str(exc)}, user_id)

    @mcp.tool(
        name="get_devices",
        annotations={
            "title": "List Available Playback Devices",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    def get_devices(
        user_id: Annotated[str, Field(description="Spotify user ID. Defaults to SPOTIFY_USER_ID env var.")] = DEFAULT_USER_ID,
    ) -> dict:
        """List all Spotify-connected devices available for playback.

        Returns a list of devices with their id, name, type, is_active, and
        volume_percent. Use a device_id from this list with play_track or
        play_playlist_or_album to target a specific device.
        """
        logger.debug("[Tool] get_devices: user_id=%s", user_id)
        try:
            with make_client(user_id) as client:
                result = _make_tools(client, user_id).get_devices()
            logger.info("[Tool] get_devices success: user_id=%s", user_id)
            return result
        except Exception as exc:
            logger.error("[Tool] get_devices failed: %s", exc)
            return enrich_auth_error({"error": str(exc)}, user_id)

    @mcp.tool(
        name="play_track",
        annotations={
            "title": "Play a Spotify Track",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    )
    def play_track(
        uri: Annotated[str, Field(description="Spotify track URI to play. Format: 'spotify:track:<id>'.")],
        device_id: Annotated[Optional[str], Field(description="Spotify device ID to play on. Use get_devices to list available IDs. Defaults to the currently active device.")] = None,
        user_id: Annotated[str, Field(description="Spotify user ID. Defaults to SPOTIFY_USER_ID env var.")] = DEFAULT_USER_ID,
    ) -> dict:
        """Start playing a specific Spotify track. Requires Spotify Premium.

        If no device is active, returns an error with available_devices so you
        can retry with a device_id, or prompt the user to open Spotify first.
        """
        logger.debug("[Tool] play_track: uri=%r device_id=%r user_id=%s", uri, device_id, user_id)
        try:
            with make_client(user_id) as client:
                result = _make_tools(client, user_id).play_track(uri, device_id=device_id)
            logger.info("[Tool] play_track success: uri=%r user_id=%s", uri, user_id)
            return result
        except Exception as exc:
            logger.error("[Tool] play_track failed: %s", exc)
            return enrich_auth_error({"error": str(exc)}, user_id)

    @mcp.tool(
        name="play_playlist_or_album",
        annotations={
            "title": "Play a Spotify Playlist or Album",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    )
    def play_playlist_or_album(
        context_uri: Annotated[str, Field(description="Spotify context URI to play. Supports playlists ('spotify:playlist:<id>') and albums ('spotify:album:<id>').")],
        device_id: Annotated[Optional[str], Field(description="Spotify device ID to play on. Use get_devices to list available IDs. Defaults to the currently active device.")] = None,
        user_id: Annotated[str, Field(description="Spotify user ID. Defaults to SPOTIFY_USER_ID env var.")] = DEFAULT_USER_ID,
    ) -> dict:
        """Start playing a Spotify playlist or album. Requires Spotify Premium.

        If no device is active, returns an error with available_devices so you
        can retry with a device_id, or prompt the user to open Spotify first.
        """
        logger.debug("[Tool] play_playlist_or_album: context_uri=%r device_id=%r user_id=%s", context_uri, device_id, user_id)
        try:
            with make_client(user_id) as client:
                result = _make_tools(client, user_id).play_playlist_or_album(context_uri, device_id=device_id)
            logger.info("[Tool] play_playlist_or_album success: context_uri=%r user_id=%s", context_uri, user_id)
            return result
        except Exception as exc:
            logger.error("[Tool] play_playlist_or_album failed: %s", exc)
            return enrich_auth_error({"error": str(exc)}, user_id)

    @mcp.tool(
        name="search",
        annotations={
            "title": "Search Spotify Catalogue",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    def search(
        query: Annotated[str, Field(description="Search query string.")],
        types: Annotated[
            List[str],
            Field(description="Item types to search. Valid values: 'track', 'album', 'artist', 'playlist'. Defaults to ['track']."),
        ] = ["track"],
        limit: Annotated[int, Field(ge=1, le=50, description="Max results per type (1–50). Defaults to 5.")] = 5,
        user_id: Annotated[str, Field(description="Spotify user ID. Defaults to SPOTIFY_USER_ID env var.")] = DEFAULT_USER_ID,
    ) -> dict:
        """Search the Spotify catalogue for tracks, albums, artists, or playlists.

        Returns a dict keyed by type (e.g. 'tracks', 'albums'), each containing
        a list of simplified items with name, uri, and relevant metadata.
        """
        logger.debug("[Tool] search: query=%r types=%s limit=%d user_id=%s", query, types, limit, user_id)
        try:
            with make_client(user_id) as client:
                result =_make_tools(client, user_id).search_item(query, types=types, limit=limit)
            logger.info("[Tool] search success: query=%r user_id=%s", query, user_id)
            return result
        except Exception as exc:
            logger.error("[Tool] search failed: %s", exc)
            return enrich_auth_error({"error": str(exc)}, user_id)


    @mcp.tool(
        name="pause_playback",
        annotations={
            "title": "Pause Spotify Playback",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    def pause_playback(
        user_id: Annotated[str, Field(description="Spotify user ID. Defaults to SPOTIFY_USER_ID env var.")] = DEFAULT_USER_ID,
    ) -> dict:
        """Pause the current Spotify playback. Requires Spotify Premium. Safe to call when already paused."""
        logger.debug("[Tool] pause_playback: user_id=%s", user_id)
        try:
            with make_client(user_id) as client:
                result = _make_tools(client, user_id).pause()
            logger.info("[Tool] pause_playback success: user_id=%s", user_id)
            return result
        except Exception as exc:
            logger.error("[Tool] pause_playback failed: %s", exc)
            return enrich_auth_error({"error": str(exc)}, user_id)

    @mcp.tool(
        name="skip_track",
        annotations={
            "title": "Skip to Next Track",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    )
    def skip_track(
        user_id: Annotated[str, Field(description="Spotify user ID. Defaults to SPOTIFY_USER_ID env var.")] = DEFAULT_USER_ID,
    ) -> dict:
        """Skip to the next track in the Spotify queue. Requires Spotify Premium."""
        logger.debug("[Tool] skip_track: user_id=%s", user_id)
        try:
            with make_client(user_id) as client:
                result = _make_tools(client, user_id).skip()
            logger.info("[Tool] skip_track success: user_id=%s", user_id)
            return result
        except Exception as exc:
            logger.error("[Tool] skip_track failed: %s", exc)
            return enrich_auth_error({"error": str(exc)}, user_id)

    @mcp.tool(
        name="set_volume",
        annotations={
            "title": "Set Playback Volume",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    def set_volume(
        volume_percent: Annotated[int, Field(ge=0, le=100, description="Target volume level from 0 (mute) to 100 (max).")],
        user_id: Annotated[str, Field(description="Spotify user ID. Defaults to SPOTIFY_USER_ID env var.")] = DEFAULT_USER_ID,
    ) -> dict:
        """Set the Spotify playback volume. Requires Spotify Premium."""
        logger.debug("[Tool] set_volume: volume_percent=%d user_id=%s", volume_percent, user_id)
        try:
            with make_client(user_id) as client:
                result = _make_tools(client, user_id).set_volume(volume_percent)
            logger.info("[Tool] set_volume success: volume_percent=%d user_id=%s", volume_percent, user_id)
            return result
        except Exception as exc:
            logger.error("[Tool] set_volume failed: %s", exc)
            return enrich_auth_error({"error": str(exc)}, user_id)

    @mcp.tool(
        name="add_to_queue",
        annotations={
            "title": "Add Track to Queue",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    )
    def add_to_queue(
        uri: Annotated[str, Field(description="Spotify track URI to enqueue. Format: 'spotify:track:<id>'.")],
        user_id: Annotated[str, Field(description="Spotify user ID. Defaults to SPOTIFY_USER_ID env var.")] = DEFAULT_USER_ID,
    ) -> dict:
        """Add a Spotify track to the end of the current playback queue. Requires Spotify Premium."""
        logger.debug("[Tool] add_to_queue: uri=%r user_id=%s", uri, user_id)
        try:
            with make_client(user_id) as client:
                result = _make_tools(client, user_id).add_to_queue(uri)
            logger.info("[Tool] add_to_queue success: uri=%r user_id=%s", uri, user_id)
            return result
        except Exception as exc:
            logger.error("[Tool] add_to_queue failed: %s", exc)
            return enrich_auth_error({"error": str(exc)}, user_id)

    @mcp.tool(
        name="create_playlist",
        annotations={
            "title": "Create Spotify Playlist",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    )
    def create_playlist(
        name: Annotated[str, Field(min_length=1, max_length=100, description="Name for the new playlist.")],
        track_uris: Annotated[List[str], Field(description="List of Spotify track URIs to add. Each must be 'spotify:track:<id>'.")],
        description: Annotated[str, Field(default="", max_length=300, description="Optional playlist description.")] = "",
        user_id: Annotated[str, Field(description="Spotify user ID. Defaults to SPOTIFY_USER_ID env var.")] = DEFAULT_USER_ID,
    ) -> dict:
        """Create a new Spotify playlist and populate it with the given tracks. Requires OAuth tokens."""
        logger.debug("[Tool] create_playlist: name=%r user_id=%s", name, user_id)
        try:
            with make_client(user_id) as client:
                result = _make_tools(client, user_id).create_playlist(name, track_uris, description)
            logger.info("[Tool] create_playlist success: name=%r user_id=%s", name, user_id)
            return result
        except Exception as exc:
            logger.error("[Tool] create_playlist failed: %s", exc)
            return enrich_auth_error({"error": str(exc)}, user_id)
