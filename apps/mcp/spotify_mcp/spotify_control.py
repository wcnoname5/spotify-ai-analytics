"""MCP tools that talk to the live Spotify Web API (playback + playlists)."""
from typing import Annotated, List, Optional
from loguru import logger

from pydantic import Field
from fastmcp import FastMCP

from spotify_mcp.utils import to_error_response
from spotify_mcp.config import (
    DB_PATH,
    DEFAULT_USER_ID,
    TOKENS_DB,
    get_client_id,
    get_fernet_key,
    make_client,
)

def _make_tools(client, user_id: str):
    '''
    Factory for `SpotifyPlaybackTools` instance to avoid circular imports. Passes through the shared client and config.
    '''
    from spotify_core.spotify_utils.spotify_facade import SpotifyToolFacade
    return SpotifyToolFacade(client, DB_PATH, TOKENS_DB, user_id, get_client_id(), get_fernet_key())


def _list_devices(user_id: str) -> list:
    """Best-effort device list for enriching NoActiveDevice errors."""
    with make_client(user_id) as client:
        return _make_tools(client, user_id).get_devices().get("devices", [])


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
        try:
            with make_client(user_id) as client:
                result = _make_tools(client, user_id).get_now_playing()
            logger.debug("[Tool] get_now_playing success: user_id={}", user_id)
            return result
        except Exception as exc:
            logger.error("[Tool] get_now_playing failed: {}", exc)
            return to_error_response(exc, user_id, list_devices=lambda: _list_devices(user_id))

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
        try:
            with make_client(user_id) as client:
                result = _make_tools(client, user_id).get_devices()
            logger.debug("[Tool] get_devices success: user_id={}", user_id)
            return result
        except Exception as exc:
            logger.error("[Tool] get_devices failed: {}", exc)
            return to_error_response(exc, user_id, list_devices=lambda: _list_devices(user_id))

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
        try:
            with make_client(user_id) as client:
                result = _make_tools(client, user_id).play_track(uri, device_id=device_id)
            logger.debug("[Tool] play_track success: uri={!r} user_id={}", uri, user_id)
            return result
        except Exception as exc:
            logger.error("[Tool] play_track failed: {}", exc)
            return to_error_response(exc, user_id, list_devices=lambda: _list_devices(user_id))

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
        try:
            with make_client(user_id) as client:
                result = _make_tools(client, user_id).play_playlist_or_album(context_uri, device_id=device_id)
            logger.debug("[Tool] play_playlist_or_album success: context_uri={!r} user_id={}", context_uri, user_id)
            return result
        except Exception as exc:
            logger.error("[Tool] play_playlist_or_album failed: {}", exc)
            return to_error_response(exc, user_id, list_devices=lambda: _list_devices(user_id))

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
        try:
            with make_client(user_id) as client:
                result =_make_tools(client, user_id).search_item(query, types=types, limit=limit)
            logger.debug("[Tool] search success: query={!r} user_id={}", query, user_id)
            return result
        except Exception as exc:
            logger.error("[Tool] search failed: {}", exc)
            return to_error_response(exc, user_id, list_devices=lambda: _list_devices(user_id))


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
        try:
            with make_client(user_id) as client:
                result = _make_tools(client, user_id).pause()
            logger.debug("[Tool] pause_playback success: user_id={}", user_id)
            return result
        except Exception as exc:
            logger.error("[Tool] pause_playback failed: {}", exc)
            return to_error_response(exc, user_id, list_devices=lambda: _list_devices(user_id))

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
        try:
            with make_client(user_id) as client:
                result = _make_tools(client, user_id).skip()
            logger.debug("[Tool] skip_track success: user_id={}", user_id)
            return result
        except Exception as exc:
            logger.error("[Tool] skip_track failed: {}", exc)
            return to_error_response(exc, user_id, list_devices=lambda: _list_devices(user_id))

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
        try:
            with make_client(user_id) as client:
                result = _make_tools(client, user_id).set_volume(volume_percent)
            logger.debug("[Tool] set_volume success: volume_percent={} user_id={}", volume_percent, user_id)
            return result
        except Exception as exc:
            logger.error("[Tool] set_volume failed: {}", exc)
            return to_error_response(exc, user_id, list_devices=lambda: _list_devices(user_id))

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
        try:
            with make_client(user_id) as client:
                result = _make_tools(client, user_id).add_to_queue(uri)
            logger.debug("[Tool] add_to_queue success: uri={!r} user_id={}", uri, user_id)
            return result
        except Exception as exc:
            logger.error("[Tool] add_to_queue failed: {}", exc)
            return to_error_response(exc, user_id, list_devices=lambda: _list_devices(user_id))

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
        try:
            with make_client(user_id) as client:
                result = _make_tools(client, user_id).create_playlist(name, track_uris, description)
            logger.debug("[Tool] create_playlist success: name={!r} user_id={}", name, user_id)
            return result
        except Exception as exc:
            logger.error("[Tool] create_playlist failed: {}", exc)
            return to_error_response(exc, user_id, list_devices=lambda: _list_devices(user_id))
