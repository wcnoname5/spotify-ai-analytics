"""Spotify AI Analytics MCP Server.

Exposes Spotify history analytics, playback control, and long-term memory
as MCP tools consumable by Claude Desktop / Claude Code.

Required environment variables:
    SPOTIFY_CLIENT_ID   — Spotify app client ID
    TOKEN_ENCRYPT_KEY   — Fernet key bytes (base64-encoded) for token encryption

Run:
    uv run python apps/mcp/server.py
"""
import logging
import os
from typing import Annotated, List, Optional

from pydantic import Field

from contextlib import asynccontextmanager

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from spotify_mcp.utils import enrich_auth_error, utc_iso_to_local
from spotify_core.db.queries import is_history_empty
from spotify_core.db.migrations import init_history_db, init_tokens_db, init_ltm_db
from spotify_core.config import settings

load_dotenv()

import sys

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "DEBUG"),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Configuration
# ------------------------------------------------------------------

CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "")
_raw_key = os.getenv("TOKEN_ENCRYPT_KEY", "")
FERNET_KEY: bytes = _raw_key.encode() if _raw_key else b""

DB_PATH = str(settings.history_db_path)
TOKENS_DB = str(settings.tokens_db_path)
LTM_DB = str(settings.ltm_db_path)
DEFAULT_USER_ID = settings.spotify_user_id

# ------------------------------------------------------------------
# Startup check
# ------------------------------------------------------------------

if not CLIENT_ID:
    logger.warning(
        "SPOTIFY_CLIENT_ID is not set. "
        "Set it in .env or pass it as an environment variable."
    )
if not FERNET_KEY:
    logger.warning(
        "TOKEN_ENCRYPT_KEY is not set. "
        "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
    )

# Check whether tokens exist (non-fatal — user may not have authed yet)
try:
    from spotify_core.spotify_client.token_store import load_tokens
    _token_check = load_tokens(TOKENS_DB, DEFAULT_USER_ID, FERNET_KEY) if FERNET_KEY else None
    if _token_check is None:
        logger.warning(
            "No Spotify tokens found. Run OAuth first:\n"
            "  uv run python scripts/setup.py",
        )
except Exception as _e:
    logger.debug("Token check skipped: %s", _e)

# ------------------------------------------------------------------
# MCP Server
# ------------------------------------------------------------------

_EMPTY_DB_RESPONSE = {
    "warning": "No listening history in the local database.",
    "next_steps": [
        "Option A — import Spotify JSON export (recommended, full history):",
        "  1. Download from https://www.spotify.com/account/privacy/ (takes a few days)",
        "  2. Place Streaming_History_Audio_*.json files in data/spotify_history/",
        "  3. uv run python scripts/setup.py",
        "Option B — sync recent 50 plays from Spotify API (instant):",
        "  uv run python scripts/sync_api.py",
    ],
}

# Tools that require Spotify Premium — removed from the tool list for free accounts.
_PREMIUM_TOOLS = ["play_track", "pause_playback", "skip_track", "set_volume", "add_to_queue"]


def _get_account_product() -> Optional[str]:
    """Return the Spotify account product type ('premium', 'free', …), or None if unavailable.

    Fails silently — the lifespan caller must treat None as "unknown, keep all tools".
    """
    if not FERNET_KEY or not CLIENT_ID:
        return None
    try:
        from spotify_core.spotify_client.token_store import load_tokens
        if load_tokens(TOKENS_DB, DEFAULT_USER_ID, FERNET_KEY) is None:
            return None
        from spotify_core.spotify_client.client import SpotifyClient
        with SpotifyClient(TOKENS_DB, DEFAULT_USER_ID, CLIENT_ID, FERNET_KEY) as client:
            profile = client.get_current_user()
            return profile.get("product")
    except Exception as exc:
        logger.debug("Account product check skipped: %s", exc)
        return None


def _ensure_dbs_initialized() -> Optional[str]:
    """Ensure all three DB files exist with their schema initialised.

    Idempotent — safe to call on every startup. Returns None on success or a
    human-readable error string on failure (so the lifespan can log it without
    crashing the server).
    """
    try:
        init_history_db(DB_PATH)
        init_tokens_db(TOKENS_DB)
        init_ltm_db(LTM_DB)
        return None
    except Exception as exc:
        return (
            f"Failed to initialise local databases: {exc}\n"
            f"  history: {DB_PATH}\n"
            f"  tokens:  {TOKENS_DB}\n"
            f"  ltm:     {LTM_DB}\n"
            "Try running setup manually: uv run python scripts/setup.py"
        )


@asynccontextmanager
async def lifespan(server: FastMCP):
    # Step 1: Make sure every DB file exists with its schema before any tool runs.
    # Without this, tools like remember_preference / get_top_tracks crash with
    # "no such table" errors that don't tell the user what to do.
    db_err = _ensure_dbs_initialized()
    if db_err:
        logger.error(db_err)

    # Step 2: Run setup diagnostics and log any outstanding actions (tokens, JSON import…).
    result = setup_check()
    if not result["ready"]:
        logger.warning(
            "Server not fully configured. Outstanding actions:\n  - %s",
            "\n  - ".join(result["actions_needed"]),
        )
    else:
        logger.info("MCP server ready: all checks passed.")

    # Check account tier and remove Premium-only tools for free accounts.
    # Fail-open: if the check fails (no tokens yet, network error), keep all tools registered.
    product = _get_account_product()
    if product is not None and product != "premium":
        for tool_name in _PREMIUM_TOOLS:
            server.remove_tool(tool_name)
        logger.info(
            "Spotify account type is %r — playback control tools removed (require Premium).",
            product,
        )
    elif product == "premium":
        logger.info("Spotify Premium account confirmed — all tools enabled.")
    else:
        logger.debug("Account type unknown — all tools registered (fail-open).")

    yield


mcp = FastMCP("spotify_mcp", lifespan=lifespan)


@mcp.tool(
    name="setup_check",
    annotations={
        "title": "Check Server Setup",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
def setup_check() -> dict:
    """Diagnose the MCP server configuration. Call this first if something isn't working.

    Returns a structured report of what is configured and what actions are still needed,
    in the order they must be completed.

    Returns:
        {
            "ready": bool,
            "checks": dict[str, bool],
            "actions_needed": list[str],
            "message": str,
        }
    """
    checks: dict[str, bool] = {}
    actions: list[str] = []

    checks["spotify_client_id"] = bool(CLIENT_ID)
    if not CLIENT_ID:
        actions.append(
            "Set SPOTIFY_CLIENT_ID in .env\n"
            "  → Create an app at https://developer.spotify.com/dashboard\n"
            "  → Copy the Client ID into your .env file"
        )

    checks["token_encrypt_key"] = bool(FERNET_KEY)

    if not FERNET_KEY:
        # --auth also initializes the DB and auto-generates the key — one command covers everything.
        actions.append(
            "Run setup — auto-generates TOKEN_ENCRYPT_KEY, initializes DB, and connects Spotify:\n"
            "  uv run python scripts/setup.py"
        )
    else:
        ltm_exists = os.path.exists(LTM_DB)
        checks["ltm_db_exists"] = ltm_exists
        if not ltm_exists:
            actions.append(
                "Long-term memory DB not found. It will be auto-created on first use, "
                "but run scripts/setup.py to initialise it explicitly."
            )

        db_exists = os.path.exists(DB_PATH)
        checks["history_db_exists"] = db_exists

        checks["tokens_exist"] = False
        try:
            from spotify_core.spotify_client.token_store import load_tokens
            tokens = load_tokens(TOKENS_DB, DEFAULT_USER_ID, FERNET_KEY)
            checks["tokens_exist"] = tokens is not None
        except Exception:
            pass

        if not db_exists or not checks["tokens_exist"]:
            actions.append(
                "Initialize DB and connect Spotify account (one command, opens browser):\n"
                "  uv run python scripts/setup.py"
            )
        else:
            has_data = not is_history_empty(DB_PATH)
            checks["history_db_has_data"] = has_data
            if not has_data:
                actions.append(
                    "Load listening history — choose one:\n"
                    "  A) Full export: place Streaming_History_Audio_*.json files in data/spotify_history/, then uv run python scripts/setup.py\n"
                    "     (download from https://www.spotify.com/account/privacy/)\n"
                    "  B) Recent plays: uv run python scripts/sync_api.py"
                )

    ready = len(actions) == 0
    return {
        "ready": ready,
        "checks": checks,
        "actions_needed": actions,
        "message": (
            "All set! MCP server is fully configured."
            if ready
            else f"{len(actions)} action(s) required to complete setup."
        ),
    }


# ------------------------------------------------------------------
# History sync tools
# ------------------------------------------------------------------


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


# ------------------------------------------------------------------
# Analytics query tools
# ------------------------------------------------------------------

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
        return [_EMPTY_DB_RESPONSE]
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
        return [_EMPTY_DB_RESPONSE]
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
            "earliest_played_at": str | None,  # local timezone ISO
            "latest_played_at": str | None,    # local timezone ISO
        }
        If the DB is empty, returns {"warning": ..., "next_steps": [...]}.
    """
    if is_history_empty(DB_PATH):
        return _EMPTY_DB_RESPONSE
    from spotify_core.db.queries import get_listening_summary as _summary
    result = dict(_summary(DB_PATH))
    result["earliest_played_at"] = utc_iso_to_local(result.get("earliest_played_at"))
    result["latest_played_at"] = utc_iso_to_local(result.get("latest_played_at"))
    return result


# ------------------------------------------------------------------
# Playback control tools
# ------------------------------------------------------------------


def _make_client(user_id: str):
    from spotify_core.spotify_client.client import SpotifyClient
    return SpotifyClient(TOKENS_DB, user_id, CLIENT_ID, FERNET_KEY)


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

    Args:
        user_id: Spotify user ID. Defaults to SPOTIFY_USER_ID env var.

    Returns:
        Dict with track info (track_name, artist_name, album, progress_ms, duration_ms, uri),
        or {"status": "nothing_playing"}, or {"error": str, "requires_auth": bool}.
    """
    try:
        from spotify_core.agent.playback_tools import SpotifyPlaybackTools
        with _make_client(user_id) as client:
            tools = SpotifyPlaybackTools(client, DB_PATH, TOKENS_DB, user_id, CLIENT_ID, FERNET_KEY)
            return enrich_auth_error(tools.get_now_playing(), user_id)
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
    uri: Annotated[str, Field(description="Spotify track URI to play. Format: 'spotify:track:<id>', e.g. 'spotify:track:4iV5W9uYEdYUVa79Axb7Rh'.")],
    user_id: Annotated[str, Field(description="Spotify user ID. Defaults to SPOTIFY_USER_ID env var.")] = DEFAULT_USER_ID,
) -> dict:
    """Start playing a specific Spotify track on the active device. Requires Spotify Premium.

    To get a track URI, use get_top_tracks or search Spotify. Each call restarts playback
    from the beginning of the track.

    Args:
        uri: Spotify track URI (format: 'spotify:track:<id>').
        user_id: Spotify user ID. Defaults to SPOTIFY_USER_ID env var.

    Returns:
        {"status": "playing", "uri": str} or {"error": str, "requires_auth": bool}.
    """
    try:
        from spotify_core.agent.playback_tools import SpotifyPlaybackTools
        with _make_client(user_id) as client:
            tools = SpotifyPlaybackTools(client, DB_PATH, TOKENS_DB, user_id, CLIENT_ID, FERNET_KEY)
            return enrich_auth_error(tools.play_track(uri), user_id)
    except Exception as exc:
        logger.error("play_track failed: %s", exc)
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
    """Pause the current Spotify playback. Requires Spotify Premium.

    Safe to call when already paused.

    Args:
        user_id: Spotify user ID. Defaults to SPOTIFY_USER_ID env var.

    Returns:
        {"status": "paused"} or {"error": str, "requires_auth": bool}.
    """
    try:
        from spotify_core.agent.playback_tools import SpotifyPlaybackTools
        with _make_client(user_id) as client:
            tools = SpotifyPlaybackTools(client, DB_PATH, TOKENS_DB, user_id, CLIENT_ID, FERNET_KEY)
            return enrich_auth_error(tools.pause(), user_id)
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
    """Skip to the next track in the Spotify queue. Requires Spotify Premium.

    Each call advances the queue by one track.

    Args:
        user_id: Spotify user ID. Defaults to SPOTIFY_USER_ID env var.

    Returns:
        {"status": "skipped"} or {"error": str, "requires_auth": bool}.
    """
    try:
        from spotify_core.agent.playback_tools import SpotifyPlaybackTools
        with _make_client(user_id) as client:
            tools = SpotifyPlaybackTools(client, DB_PATH, TOKENS_DB, user_id, CLIENT_ID, FERNET_KEY)
            return enrich_auth_error(tools.skip(), user_id)
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
    """Set the Spotify playback volume. Requires Spotify Premium.

    Setting the same volume twice has no additional effect.

    Args:
        volume_percent: Target volume level 0–100.
        user_id: Spotify user ID. Defaults to SPOTIFY_USER_ID env var.

    Returns:
        {"status": "volume_set", "volume_percent": int} or {"error": str, "requires_auth": bool}.
    """
    try:
        from spotify_core.agent.playback_tools import SpotifyPlaybackTools
        with _make_client(user_id) as client:
            tools = SpotifyPlaybackTools(client, DB_PATH, TOKENS_DB, user_id, CLIENT_ID, FERNET_KEY)
            return enrich_auth_error(tools.set_volume(volume_percent), user_id)
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
    uri: Annotated[str, Field(description="Spotify track URI to enqueue. Format: 'spotify:track:<id>', e.g. 'spotify:track:4iV5W9uYEdYUVa79Axb7Rh'.")],
    user_id: Annotated[str, Field(description="Spotify user ID. Defaults to SPOTIFY_USER_ID env var.")] = DEFAULT_USER_ID,
) -> dict:
    """Add a Spotify track to the end of the current playback queue. Requires Spotify Premium.

    Calling this multiple times with the same URI adds duplicate entries to the queue.

    Args:
        uri: Spotify track URI (format: 'spotify:track:<id>').
        user_id: Spotify user ID. Defaults to SPOTIFY_USER_ID env var.

    Returns:
        {"status": "queued", "uri": str} or {"error": str, "requires_auth": bool}.
    """
    try:
        from spotify_core.agent.playback_tools import SpotifyPlaybackTools
        with _make_client(user_id) as client:
            tools = SpotifyPlaybackTools(client, DB_PATH, TOKENS_DB, user_id, CLIENT_ID, FERNET_KEY)
            return enrich_auth_error(tools.add_to_queue(uri), user_id)
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
    name: Annotated[str, Field(min_length=1, max_length=100, description="Name for the new playlist, e.g. 'My Top 2024 Tracks'.")],
    track_uris: Annotated[List[str], Field(description="List of Spotify track URIs to add. Each must be in 'spotify:track:<id>' format.")],
    description: Annotated[str, Field(default="", max_length=300, description="Optional playlist description shown on Spotify.")] = "",
    user_id: Annotated[str, Field(description="Spotify user ID. Defaults to SPOTIFY_USER_ID env var.")] = DEFAULT_USER_ID,
) -> dict:
    """Create a new Spotify playlist and populate it with the given tracks.

    Each call creates a new playlist even if one with the same name already exists.
    Requires Spotify OAuth tokens.

    Args:
        name: Playlist name (1–100 chars).
        track_uris: List of Spotify track URIs in 'spotify:track:<id>' format.
        description: Optional playlist description (max 300 chars).
        user_id: Spotify user ID. Defaults to SPOTIFY_USER_ID env var.

    Returns:
        {"playlist_id": str, "url": str, "track_count": int} or {"error": str, "requires_auth": bool}.
    """
    try:
        from spotify_core.agent.playback_tools import SpotifyPlaybackTools
        with _make_client(user_id) as client:
            tools = SpotifyPlaybackTools(client, DB_PATH, TOKENS_DB, user_id, CLIENT_ID, FERNET_KEY)
            return enrich_auth_error(tools.create_playlist(name, track_uris, description), user_id)
    except Exception as exc:
        logger.error("create_playlist failed: %s", exc)
        return enrich_auth_error({"error": str(exc)}, user_id)


# ------------------------------------------------------------------
# Long-term memory tools
# ------------------------------------------------------------------


@mcp.tool(
    name="remember_preference",
    annotations={
        "title": "Store User Preference",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
def remember_preference(
    key: Annotated[str, Field(min_length=1, max_length=100, description="Preference key/name, e.g. 'favorite_genre', 'preferred_language', 'mood_for_working'.")],
    value: Annotated[str, Field(min_length=1, max_length=2000, description="Preference value as a string. May be a short label ('jazz') or a longer structured note (e.g. a ranked list of tracks).")],
    user_id: Annotated[str, Field(description="Spotify user ID. Defaults to SPOTIFY_USER_ID env var.")] = DEFAULT_USER_ID,
) -> dict:
    """Store a user preference in long-term memory. Persists across all future conversations.

    Writing the same key again overwrites the previous value.
    Use get_memory_summary to read back all stored preferences.

    Args:
        key: Preference name (e.g. 'favorite_genre', 'mood_for_working').
        value: Preference value as a string (up to 2000 chars).
        user_id: Spotify user ID. Defaults to SPOTIFY_USER_ID env var.

    Returns:
        {"status": "saved", "key": str, "value": str} or {"error": str}.
    """
    try:
        from spotify_core.memory import get_store, get_user_namespace
        ns = get_user_namespace(user_id, "preferences")
        with get_store(LTM_DB) as store:
            store.put(ns, key, {"value": value})
        return {"status": "saved", "key": key, "value": value}
    except Exception as exc:
        logger.error("remember_preference failed: %s", exc)
        return {"error": str(exc)}


@mcp.tool(
    name="get_memory_summary",
    annotations={
        "title": "Get Long-Term Memory Summary",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
def get_memory_summary(
    user_id: Annotated[str, Field(description="Spotify user ID. Defaults to SPOTIFY_USER_ID env var.")] = DEFAULT_USER_ID,
) -> dict:
    """Return all stored preferences, history facts, and feedback for a user from long-term memory.

    Use this at the start of a conversation to recall what is known about the user.
    Store new information with remember_preference.

    Args:
        user_id: Spotify user ID. Defaults to SPOTIFY_USER_ID env var.

    Returns:
        {"preferences": dict[str, any], "history_facts": dict[str, any], "feedback": dict[str, any]}
    """
    try:
        from spotify_core.memory import get_store, get_user_namespace
        summary: dict = {}
        with get_store(LTM_DB) as store:
            for key in ("preferences", "history_facts", "feedback"):
                ns = get_user_namespace(user_id, key)
                items = store.search(ns)
                summary[key] = {item.key: item.value for item in items}
        return summary
    except Exception as exc:
        logger.error("get_memory_summary failed: %s", exc)
        return {"error": str(exc)}


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------

def main():
    mcp.run()


if __name__ == "__main__":
    main()
