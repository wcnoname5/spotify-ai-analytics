"""MCP tools backed by the local SQLite databases (history.db).

Covers DB write tools (sync_history, import_history_from_json) and analytics
read tools (get_recent_playback, get_top_artists/tracks, get_listening_summary).
"""
from typing import Annotated, Optional
from loguru import logger

from pydantic import Field
from fastmcp import FastMCP

from spotify_core.db.queries import is_history_empty
from spotify_mcp.utils import to_error_response, utc_iso_to_local
from spotify_mcp.config import (
    DB_PATH,
    DEFAULT_USER_ID,
    EMPTY_DB_RESPONSE,
    TOKENS_DB,
    get_client_id,
    get_fernet_key,
)

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
            result = sync_api_to_db(
                db_path=DB_PATH,
                tokens_db_path=TOKENS_DB,
                user_id=user_id,
                client_id=get_client_id(),
                fernet_key=get_fernet_key(),
            )
            logger.debug("[Tool] sync_history success: inserted={}", result.get("inserted"))
            return result
        except Exception as exc:
            logger.error("[Tool] sync_history failed: {}", exc)
            return to_error_response(exc, user_id)

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
        try:
            from spotify_core.db.pipeline import import_json_to_db
            result = import_json_to_db(json_dir=json_dir, db_path=DB_PATH)
            logger.debug("[Tool] import_history_from_json success: inserted={}", result.get("inserted"))
            return result
        except Exception as exc:
            logger.error("[Tool] import_history_from_json failed: {}", exc)
            return {"error": str(exc)}

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
        user_id: Annotated[str, Field(description="Spotify user ID. Defaults to SPOTIFY_USER_ID env var.")] = DEFAULT_USER_ID,
    ) -> dict:
        """Sync recent plays from the Spotify API into the local DB, then return them.

        Use this when you need to see what was played recently with full track details.
        Unlike sync_history (which only returns counts), this returns the actual track list.
        Requires Spotify OAuth tokens.

        Args:
            limit: Number of recent plays to return (1–50, default 10).
            user_id: Spotify user ID. Defaults to SPOTIFY_USER_ID env var.

        Returns:
            {
                "tracks": [{"track_name": str, "artist_name": str, "album_name": str,
                            "played_at": str, "ms_played": int, "track_id": str}],
                "synced": {"inserted": int, "skipped_duplicated": int, "cursor_ms": int},
            }
            or {"error": str, "requires_auth": bool}.
            track_id is the Spotify URI — pass it to play_track or add_to_queue.
        """
        try:
            from spotify_core.db.pipeline import sync_api_to_db
            from spotify_core.db.queries import get_recent_plays

            sync_result = sync_api_to_db(
                db_path=DB_PATH,
                tokens_db_path=TOKENS_DB,
                user_id=user_id,
                client_id=get_client_id(),
                fernet_key=get_fernet_key(),
            )
            tracks = get_recent_plays(DB_PATH, limit=limit)
            for track in tracks:
                track["played_at"] = utc_iso_to_local(track.get("played_at"))
            logger.debug(
                "[Tool] get_recent_playback success: returned %d, synced %d tracks",
                len(tracks),
                sync_result.get("inserted")
            )
            return {"tracks": tracks, "synced": sync_result}
        except Exception as exc:
            logger.error("[Tool] get_recent_playback failed: {}", exc)
            return to_error_response(exc, user_id)

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
            List of {"artist_name": str, "total_mins": int, "play_count": int}, ordered by total_mins desc.
            If the DB is empty, returns [{"warning": ...}].
        """
        if is_history_empty(DB_PATH):
            logger.warning("[Tool] get_top_artists: history DB is empty")
            return [EMPTY_DB_RESPONSE]
        try:
            from spotify_core.db.queries import get_top_artists as _get_top_artists
            result = _get_top_artists(DB_PATH, limit=limit, start_date=start_date, end_date=end_date)
            logger.debug("[Tool] get_top_artists success: returned {} artists", len(result))
            return result
        except Exception as exc:
            logger.error("[Tool] get_top_artists failed: {}", exc)
            return [{"error": str(exc)}]

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
    ) -> list:
        """Return top tracks ranked by play count from the local history DB.

        Does not require Spotify auth — reads from the local SQLite database only.
        Use start_date/end_date to scope the ranking to a specific time window.

        Args:
            limit: Number of top tracks to return (1–100, default 10).
            start_date: Optional inclusive start date filter in YYYY-MM-DD format.
            end_date: Optional inclusive end date filter in YYYY-MM-DD format.

        Returns:
            List of {"track_id": str, "track_name": str, "artist_name": str,
            "play_count": int, "total_mins": int}, ordered by play_count desc.
            track_id is the Spotify URI — pass it to create_playlist or play_track.
            If the DB is empty, returns [{"warning": ... }].
        """
        if is_history_empty(DB_PATH):
            logger.warning("[Tool] get_top_tracks: history DB is empty")
            return [EMPTY_DB_RESPONSE]
        try:
            from spotify_core.db.queries import get_top_tracks as _get_top_tracks
            result = _get_top_tracks(DB_PATH, limit=limit, start_date=start_date, end_date=end_date)
            logger.debug("[Tool] get_top_tracks success: returned {} tracks", len(result))
            return result
        except Exception as exc:
            logger.error("[Tool] get_top_tracks failed: {}", exc)
            return [{"error": str(exc)}]


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
    def get_listening_summary(
        start_date: Annotated[Optional[str], Field(default=None, description="Filter plays on or after this date. Format: YYYY-MM-DD, e.g. '2024-01-01'.")] = None,
        end_date: Annotated[Optional[str], Field(default=None, description="Filter plays on or before this date. Format: YYYY-MM-DD, e.g. '2024-12-31'.")] = None,
    ) -> dict:
        """Return a summary of local listening history including play counts, date range, and volume stats.

        Does not require Spotify auth — reads from the local SQLite database only.
        Use start_date/end_date to scope the summary to a specific time window.

        Args:
            start_date: Optional inclusive start date filter in YYYY-MM-DD format.
            end_date: Optional inclusive end date filter in YYYY-MM-DD format.

        Returns:
            {
                "total_plays": int,
                "unique_tracks": int,
                "unique_artists": int,
                "earliest_played_at": str | None,
                "latest_played_at": str | None,
                "total_mins_played": int | None,
                "avg_mins_per_play": int | None,
                "skip_rate": float | None,
            }
            If the DB is empty, returns {"warning": ..., "next_steps": [...]}.
        """
        if is_history_empty(DB_PATH):
            logger.warning("[Tool] get_listening_summary: history DB is empty")
            return EMPTY_DB_RESPONSE
        try:
            from spotify_core.db.queries import get_listening_summary as _summary
            result = dict(_summary(DB_PATH, start_date=start_date, end_date=end_date))
            result["earliest_played_at"] = utc_iso_to_local(result.get("earliest_played_at"))
            result["latest_played_at"] = utc_iso_to_local(result.get("latest_played_at"))
            logger.debug(
                "[Tool] get_listening_summary success: total_plays=%d unique_tracks=%d unique_artists=%d",
                result["total_plays"],
                result["unique_tracks"],
                result["unique_artists"],
            )
            return result
        except Exception as exc:
            logger.error("[Tool] get_listening_summary failed: {}", exc)
            return {"error": str(exc)}

    @mcp.tool(
        name="list_reports",
        annotations={
            "title": "List Saved AI Reports",
            "readOnlyHint": True, "destructiveHint": False,
            "idempotentHint": True, "openWorldHint": False,
        },
    )
    def list_reports() -> list[dict]:
        """List saved AI report metadata (no text), newest first.

        Returns: [{"id", "style", "period_type", "start_date", "end_date",
                   "provider", "model", "generated_at", "revision_count"}, ...]
        """
        try:
            from spotify_core.db.report_store import list_reports as _list
            return _list(DB_PATH)
        except Exception as exc:
            logger.error("[Tool] list_reports failed: {}", exc)
            return [{"error": str(exc)}]

    @mcp.tool(
        name="get_report",
        annotations={
            "title": "Get a Saved AI Report",
            "readOnlyHint": True, "destructiveHint": False,
            "idempotentHint": True, "openWorldHint": False,
        },
    )
    def get_report(report_id: str) -> dict:
        """Return one saved AI report (including its markdown text) by id.

        Args:
            report_id: The report uuid from list_reports.
        """
        try:
            from spotify_core.db.report_store import get_report as _get
            row = _get(DB_PATH, report_id)
            return row if row else {"error": f"no report with id {report_id}"}
        except Exception as exc:
            logger.error("[Tool] get_report failed: {}", exc)
            return {"error": str(exc)}

    @mcp.tool(
        name="get_listening_patterns",
        annotations={
            "title": "Get Temporal Listening Patterns",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    def get_listening_patterns(
        start_date: Annotated[Optional[str], Field(default=None, description="Filter plays on or after this date. Format: YYYY-MM-DD, e.g. '2024-01-01'.")] = None,
        end_date: Annotated[Optional[str], Field(default=None, description="Filter plays on or before this date. Format: YYYY-MM-DD, e.g. '2024-12-31'.")] = None,
    ) -> dict:
        """Return temporal patterns from local listening history: peak hour, peak day, most active date, and average plays per day.

        All time-based groupings (hour, day-of-week, date) are expressed in the user's
        local timezone, inferred automatically from the most common conn_country in the DB.
        Does not require Spotify auth — reads from the local SQLite database only.
        Use start_date/end_date to scope the analysis to a specific time window.

        Args:
            start_date: Optional inclusive start date filter in YYYY-MM-DD format.
            end_date: Optional inclusive end date filter in YYYY-MM-DD format.

        Returns:
            {
                "peak_hour": int | None,                   -- local hour-of-day (0-23) with most plays
                "peak_day_of_week": str | None,            -- e.g. "Thursday" (local time)
                "most_active_date": str | None,            -- YYYY-MM-DD (local date) with most plays
                "most_active_date_play_count": int | None, -- how many plays on that date
                "most_active_date_total_mins": int | None,  -- total minutes listened on that date
                "avg_plays_per_day": float | None,         -- plays divided by distinct local calendar days
            }
            If the DB is empty, returns {"warning": ..., "next_steps": [...]}.
        """
        if is_history_empty(DB_PATH):
            logger.warning("[Tool] get_listening_patterns: history DB is empty")
            return EMPTY_DB_RESPONSE
        try:
            from spotify_core.db.queries import get_listening_patterns as _patterns
            result = _patterns(DB_PATH, start_date=start_date, end_date=end_date)
            logger.debug(
                "[Tool] get_listening_patterns success: peak_hour=%s peak_day=%s",
                result.get("peak_hour"),
                result.get("peak_day_of_week"),
            )
            return result
        except Exception as exc:
            logger.error("[Tool] get_listening_patterns failed: {}", exc)
            return {"error": str(exc)}
