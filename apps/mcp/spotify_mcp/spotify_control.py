"""MCP tools that talk to the live Spotify Web API (playback + playlists)."""
import logging
from typing import Annotated, List

from pydantic import Field
from mcp.server.fastmcp import FastMCP

from spotify_mcp.utils import enrich_auth_error
from spotify_mcp.config import (
    CLIENT_ID,
    DB_PATH,
    DEFAULT_USER_ID,
    FERNET_KEY,
    TOKENS_DB,
    make_client,
)

logger = logging.getLogger(__name__)


def _make_tools(client, user_id: str):
    from spotify_core.spotify_utils.playback_tools import SpotifyPlaybackTools
    return SpotifyPlaybackTools(client, DB_PATH, TOKENS_DB, user_id, CLIENT_ID, FERNET_KEY)


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
                return enrich_auth_error(_make_tools(client, user_id).get_now_playing(), user_id)
        except Exception as exc:
            logger.error("get_now_playing failed: %s", exc)
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
        user_id: Annotated[str, Field(description="Spotify user ID. Defaults to SPOTIFY_USER_ID env var.")] = DEFAULT_USER_ID,
    ) -> dict:
        """Start playing a specific Spotify track on the active device. Requires Spotify Premium."""
        try:
            with make_client(user_id) as client:
                return enrich_auth_error(_make_tools(client, user_id).play_track(uri), user_id)
        except Exception as exc:
            logger.error("play_track failed: %s", exc)
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
        user_id: Annotated[str, Field(description="Spotify user ID. Defaults to SPOTIFY_USER_ID env var.")] = DEFAULT_USER_ID,
    ) -> dict:
        """Start playing a Spotify playlist or album on the active device. Requires Spotify Premium."""
        try:
            with make_client(user_id) as client:
                return enrich_auth_error(_make_tools(client, user_id).play_playlist_or_album(context_uri), user_id)
        except Exception as exc:
            logger.error("play_playlist_or_album failed: %s", exc)
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
        try:
            with make_client(user_id) as client:
                return enrich_auth_error(_make_tools(client, user_id).search_item(query, types=types, limit=limit), user_id)
        except Exception as exc:
            logger.error("search failed: %s", exc)
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
        try:
            with make_client(user_id) as client:
                return enrich_auth_error(_make_tools(client, user_id).pause(), user_id)
        except Exception as exc:
            logger.error("pause_playback failed: %s", exc)
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
        try:
            with make_client(user_id) as client:
                return enrich_auth_error(_make_tools(client, user_id).skip(), user_id)
        except Exception as exc:
            logger.error("skip_track failed: %s", exc)
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
        try:
            with make_client(user_id) as client:
                return enrich_auth_error(_make_tools(client, user_id).set_volume(volume_percent), user_id)
        except Exception as exc:
            logger.error("set_volume failed: %s", exc)
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
        try:
            with make_client(user_id) as client:
                return enrich_auth_error(_make_tools(client, user_id).add_to_queue(uri), user_id)
        except Exception as exc:
            logger.error("add_to_queue failed: %s", exc)
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
        try:
            with make_client(user_id) as client:
                return enrich_auth_error(
                    _make_tools(client, user_id).create_playlist(name, track_uris, description),
                    user_id,
                )
        except Exception as exc:
            logger.error("create_playlist failed: %s", exc)
            return enrich_auth_error({"error": str(exc)}, user_id)
