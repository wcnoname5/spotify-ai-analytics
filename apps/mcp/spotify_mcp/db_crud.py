"""MCP tools backed by the local SQLite databases (history.db).

Covers DB write tools (sync_history, import_history_from_json) and analytics
read tools (get_recent_playback, get_top_artists/tracks, get_listening_summary).
"""
import logging
from typing import Annotated, Optional

from pydantic import Field
from mcp.server.fastmcp import FastMCP

from spotify_core.db.queries import is_history_empty
from spotify_mcp.utils import enrich_auth_error, utc_iso_to_local
from spotify_mcp.config import (
    CLIENT_ID,
    DB_PATH,
    DEFAULT_USER_ID,
    EMPTY_DB_RESPONSE,
    FERNET_KEY,
    TOKENS_DB,
)

logger = logging.getLogger(__name__)


def register(mcp: FastMCP) -> None:
    """Attach DB CRUD + analytics tools to the given FastMCP server."""

    @mcp.tool(
        name="sync_history",
        annotations={
            "title": "Sync Recent Listening History",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    def sync_history(
        user_id: Annotated[str, Field(description="Spotify user ID whose history to sync. Defaults to SPOTIFY_USER_ID env var.")] = DEFAULT_USER_ID,
    ) -> dict:
        """Fetch the 50 most recent Spotify plays from the Spotify API and store them in the local DB.

        Requires Spotify OAuth tokens (run scripts/setup.py first).
        Use this to keep the local DB up to date with recent plays.

        Args:
            user_id: Spotify user ID whose history to sync. Defaults to SPOTIFY_USER_ID env var.

        Returns:
            {"inserted": int, "cursor_ms": int} or {"error": str, "requires_auth": bool, "auth_command": str}.
        """
        try:
            from spotify_core.db.pipeline import sync_api_to_db
            return sync_api_to_db(
                db_path=DB_PATH,
                tokens_db_path=TOKENS_DB,
                user_id=user_id,
                client_id=CLIENT_ID,
                fernet_key=FERNET_KEY,
            )
        except Exception as exc:
            logger.error("sync_history failed: %s", exc)
            return enrich_auth_error({"error": str(exc)}, user_id)

    @mcp.tool(
        name="import_history_from_json",
        annotations={
            "title": "Import History from Spotify JSON Export",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    def import_history_from_json(
        json_dir: Annotated[str, Field(description="Path to the folder containing Spotify JSON export files named Streaming_History_Audio_*.json or Streaming_History_Video_*.json. E.g. 'data/spotify_history'.")],
    ) -> dict:
        """Bulk import Spotify streaming history from a folder of Streaming_History_*.json export files.

        Use this to load your full Spotify history from the Extended Streaming History export
        (requested from https://www.spotify.com/account/privacy/). Does not require Spotify auth.
        Duplicate records are safely skipped.

        Args:
            json_dir: Path to folder containing Spotify JSON export files.

        Returns:
            {"inserted": int, "skipped_duplicated": int, "skipped_parse_error": int}
        """
        from spotify_core.db.pipeline import import_json_to_db
        return import_json_to_db(json_dir=json_dir, db_path=DB_PATH)

    @mcp.tool(
        name="get_recent_playback",
        annotations={
            "title": "Get Recent Playback History",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    def get_recent_playback(
        limit: Annotated[int, Field(default=10, ge=1, le=50, description="Number of recent plays to return (1–50, default 10).")] = 10,
        show_track_id: Annotated[bool, Field(default=False, description="If True, include track_id (Spotify URI) in each track. Required when you intend to pass results to play_track or add_to_queue.")] = False,
        user_id: Annotated[str, Field(description="Spotify user ID. Defaults to SPOTIFY_USER_ID env var.")] = DEFAULT_USER_ID,
    ) -> dict:
        """Sync recent plays from the Spotify API into the local DB, then return them.

        Use this when you need to see what was played recently with full track details.
        Unlike sync_history (which only returns counts), this returns the actual track list.
        Requires Spotify OAuth tokens.

        Args:
            limit: Number of recent plays to return (1–50, default 10).
            show_track_id: Include Spotify track URI in results (default false).
            user_id: Spotify user ID. Defaults to SPOTIFY_USER_ID env var.

        Returns:
            {
                "tracks": [{"track_name": str, "artist_name": str, "album_name": str,
                            "played_at": str, "ms_played": int}],
                "synced": {"inserted": int, "skipped_duplicated": int, "cursor_ms": int},
            }
            plus "track_id": str per track when show_track_id is true.
            or {"error": str, "requires_auth": bool}.
        """
        try:
            from spotify_core.db.pipeline import sync_api_to_db
            from spotify_core.db.queries import get_recent_plays

            sync_result = sync_api_to_db(
                db_path=DB_PATH,
                tokens_db_path=TOKENS_DB,
                user_id=user_id,
                client_id=CLIENT_ID,
                fernet_key=FERNET_KEY,
            )
            tracks = get_recent_plays(DB_PATH, limit=limit, show_track_id=show_track_id)
            for track in tracks:
                track["played_at"] = utc_iso_to_local(track.get("played_at"))
            return {"tracks": tracks, "synced": sync_result}
        except Exception as exc:
            logger.error("get_recent_playback failed: %s", exc)
            return enrich_auth_error({"error": str(exc)}, user_id)

    @mcp.tool(
        name="get_top_artists",
        annotations={
            "title": "Get Top Artists by Listening Time",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    def get_top_artists(
        limit: Annotated[int, Field(default=10, ge=1, le=100, description="Number of top artists to return (1–100, default 10).")] = 10,
        start_date: Annotated[Optional[str], Field(default=None, description="Filter plays on or after this date. Format: YYYY-MM-DD, e.g. '2024-01-01'.")] = None,
        end_date: Annotated[Optional[str], Field(default=None, description="Filter plays on or before this date. Format: YYYY-MM-DD, e.g. '2024-12-31'.")] = None,
    ) -> list:
        """Return top artists ranked by total listening time (ms) from the local history DB.

        Does not require Spotify auth — reads from the local SQLite database only.
        Use start_date/end_date to scope the ranking to a specific time window.

        Args:
            limit: Number of top artists to return (1–100, default 10).
            start_date: Optional inclusive start date filter in YYYY-MM-DD format.
            end_date: Optional inclusive end date filter in YYYY-MM-DD format.

        Returns:
            List of {"artist_name": str, "total_ms": int, "play_count": int}, ordered by total_ms desc.
            If the DB is empty, returns [{"warning": ..., "next_steps": [...]}].
        """
        if is_history_empty(DB_PATH):
            return [EMPTY_DB_RESPONSE]
        from spotify_core.db.queries import get_top_artists as _get_top_artists
        return _get_top_artists(DB_PATH, limit=limit, start_date=start_date, end_date=end_date)

    @mcp.tool(
        name="get_top_tracks",
        annotations={
            "title": "Get Top Tracks by Play Count",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    def get_top_tracks(
        limit: Annotated[int, Field(default=10, ge=1, le=100, description="Number of top tracks to return (1–100, default 10).")] = 10,
        start_date: Annotated[Optional[str], Field(default=None, description="Filter plays on or after this date. Format: YYYY-MM-DD, e.g. '2024-01-01'.")] = None,
        end_date: Annotated[Optional[str], Field(default=None, description="Filter plays on or before this date. Format: YYYY-MM-DD, e.g. '2024-12-31'.")] = None,
        show_track_id: Annotated[bool, Field(default=False, description="If True, include track_id (Spotify URI, e.g. 'spotify:track:<id>') in each result. Required when you intend to pass results to create_playlist or play_track.")] = False,
    ) -> list:
        """Return top tracks ranked by play count from the local history DB.

        Does not require Spotify auth — reads from the local SQLite database only.
        Use start_date/end_date to scope the ranking to a specific time window.
        Set show_track_id=true when you need URIs for playlist creation or playback.

        Args:
            limit: Number of top tracks to return (1–100, default 10).
            start_date: Optional inclusive start date filter in YYYY-MM-DD format.
            end_date: Optional inclusive end date filter in YYYY-MM-DD format.
            show_track_id: Include Spotify track URI in results (default false).

        Returns:
            List of {"track_name": str, "artist_name": str, "play_count": int, "total_ms": int},
            plus "track_id": str when show_track_id is true. Ordered by play_count desc.
            If the DB is empty, returns [{"warning": ..., "next_steps": [...]}].
        """
        if is_history_empty(DB_PATH):
            return [EMPTY_DB_RESPONSE]
        from spotify_core.db.queries import get_top_tracks as _get_top_tracks
        return _get_top_tracks(DB_PATH, limit=limit, start_date=start_date, end_date=end_date, show_track_id=show_track_id)

    @mcp.tool(
        name="get_listening_summary",
        annotations={
            "title": "Get Listening History Summary",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    def get_listening_summary() -> dict:
        """Return a summary of local listening history (total plays, date range, unique artists/tracks).

        Returns:
            {
                "total_plays": int,
                "unique_tracks": int,
                "unique_artists": int,
                "earliest_played_at": str | None,
                "latest_played_at": str | None,
            }
            If the DB is empty, returns {"warning": ..., "next_steps": [...]}.
        """
        if is_history_empty(DB_PATH):
            return EMPTY_DB_RESPONSE
        from spotify_core.db.queries import get_listening_summary as _summary
        result = dict(_summary(DB_PATH))
        result["earliest_played_at"] = utc_iso_to_local(result.get("earliest_played_at"))
        result["latest_played_at"] = utc_iso_to_local(result.get("latest_played_at"))
        return result
