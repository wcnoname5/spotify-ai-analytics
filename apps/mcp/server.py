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
from typing import Optional

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from spotify_mcp.utils import enrich_auth_error, utc_iso_to_local
from spotify_core.db.queries import is_history_empty

load_dotenv()

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Configuration
# ------------------------------------------------------------------

CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "")
_raw_key = os.getenv("TOKEN_ENCRYPT_KEY", "")
FERNET_KEY: bytes = _raw_key.encode() if _raw_key else b""

DB_PATH = "data/history.db"
TOKENS_DB = "data/tokens.db"
LTM_DB = "data/ltm.db"
DEFAULT_USER_ID = os.getenv("SPOTIFY_USER_ID", "default")

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
            "  uv run python scripts/init_db.py --auth --user-id %s",
            DEFAULT_USER_ID,
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
        "  2. uv run python scripts/import_json.py --dir data/spotify_history",
        "Option B — sync recent 50 plays from Spotify API (instant):",
        "  uv run python scripts/sync_api.py --user-id <your_spotify_user_id>",
    ],
}

mcp = FastMCP("spotify-analytics")


@mcp.tool()
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
            "Run the init script — auto-generates TOKEN_ENCRYPT_KEY, initializes DB, and connects Spotify:\n"
            "  uv run python scripts/init_db.py --auth --user-id <your_spotify_username>"
        )
    else:
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
                "  uv run python scripts/init_db.py --auth --user-id <your_spotify_username>"
            )
        else:
            has_data = not is_history_empty(DB_PATH)
            checks["history_db_has_data"] = has_data
            if not has_data:
                actions.append(
                    "Load listening history — choose one:\n"
                    "  A) Full export: uv run python scripts/import_json.py --dir data/spotify_history\n"
                    "     (download from https://www.spotify.com/account/privacy/)\n"
                    "  B) Recent plays: uv run python scripts/sync_api.py --user-id <your_spotify_username>"
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


@mcp.tool()
def sync_history(user_id: str = DEFAULT_USER_ID) -> dict:
    """Fetch the 50 most recent Spotify plays and store them in the local DB.

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


@mcp.tool()
def import_history_from_json(json_dir: str) -> dict:
    """Bulk import Spotify streaming history from a folder of Streaming*.json files.

    Args:
        json_dir: Path to the folder containing Spotify JSON export files.

    Returns:
        {"inserted": int, "skipped": int}
    """
    from spotify_core.db.pipeline import import_json_to_db
    return import_json_to_db(json_dir=json_dir, db_path=DB_PATH)


# ------------------------------------------------------------------
# Analytics query tools
# ------------------------------------------------------------------


@mcp.tool()
def get_top_artists(
    limit: int = 10,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> list:
    """Return top artists by total listening time from local history DB.

    Args:
        limit: Number of artists to return (default 10).
        start_date: Optional start date filter "YYYY-MM-DD".
        end_date: Optional end date filter "YYYY-MM-DD".

    Returns:
        List of {"artist_name": str, "total_ms": int, "play_count": int}.
        If the DB is empty, returns [{"warning": ..., "next_steps": [...]}].
    """
    if is_history_empty(DB_PATH):
        return [_EMPTY_DB_RESPONSE]
    from spotify_core.db.queries import get_top_artists as _get_top_artists
    return _get_top_artists(DB_PATH, limit=limit, start_date=start_date, end_date=end_date)


@mcp.tool()
def get_top_tracks(
    limit: int = 10,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> list:
    """Return top tracks by play count from local history DB.

    Args:
        limit: Number of tracks to return (default 10).
        start_date: Optional start date filter "YYYY-MM-DD".
        end_date: Optional end date filter "YYYY-MM-DD".

    Returns:
        List of {"track_name": str, "artist_name": str, "play_count": int, "total_ms": int}.
        If the DB is empty, returns [{"warning": ..., "next_steps": [...]}].
    """
    if is_history_empty(DB_PATH):
        return [_EMPTY_DB_RESPONSE]
    from spotify_core.db.queries import get_top_tracks as _get_top_tracks
    return _get_top_tracks(DB_PATH, limit=limit, start_date=start_date, end_date=end_date)


@mcp.tool()
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


@mcp.tool()
def get_now_playing(user_id: str = DEFAULT_USER_ID) -> dict:
    """Return the currently playing Spotify track.

    Args:
        user_id: Spotify user ID. Defaults to SPOTIFY_USER_ID env var.

    Returns:
        Dict with track info, or {"status": "nothing_playing"}.
    """
    try:
        from spotify_core.agent.playback_tools import SpotifyPlaybackTools
        with _make_client(user_id) as client:
            tools = SpotifyPlaybackTools(client, DB_PATH, TOKENS_DB, user_id, CLIENT_ID, FERNET_KEY)
            return enrich_auth_error(tools.get_now_playing(), user_id)
    except Exception as exc:
        logger.error("get_now_playing failed: %s", exc)
        return enrich_auth_error({"error": str(exc)}, user_id)


@mcp.tool()
def play_track(uri: str, user_id: str = DEFAULT_USER_ID) -> dict:
    """Start playing a Spotify track (requires Premium).

    Args:
        uri: Spotify track URI e.g. "spotify:track:4iV5W9uYEdYUVa79Axb7Rh".
        user_id: Spotify user ID. Defaults to SPOTIFY_USER_ID env var.

    Returns:
        {"status": "playing", "uri": str} or {"error": str}.
    """
    try:
        from spotify_core.agent.playback_tools import SpotifyPlaybackTools
        with _make_client(user_id) as client:
            tools = SpotifyPlaybackTools(client, DB_PATH, TOKENS_DB, user_id, CLIENT_ID, FERNET_KEY)
            return enrich_auth_error(tools.play_track(uri), user_id)
    except Exception as exc:
        logger.error("play_track failed: %s", exc)
        return enrich_auth_error({"error": str(exc)}, user_id)


@mcp.tool()
def pause_playback(user_id: str = DEFAULT_USER_ID) -> dict:
    """Pause the current Spotify playback (requires Premium).

    Args:
        user_id: Spotify user ID. Defaults to SPOTIFY_USER_ID env var.

    Returns:
        {"status": "paused"} or {"error": str}.
    """
    try:
        from spotify_core.agent.playback_tools import SpotifyPlaybackTools
        with _make_client(user_id) as client:
            tools = SpotifyPlaybackTools(client, DB_PATH, TOKENS_DB, user_id, CLIENT_ID, FERNET_KEY)
            return enrich_auth_error(tools.pause(), user_id)
    except Exception as exc:
        logger.error("pause_playback failed: %s", exc)
        return enrich_auth_error({"error": str(exc)}, user_id)


@mcp.tool()
def skip_track(user_id: str = DEFAULT_USER_ID) -> dict:
    """Skip to the next Spotify track (requires Premium).

    Args:
        user_id: Spotify user ID. Defaults to SPOTIFY_USER_ID env var.

    Returns:
        {"status": "skipped"} or {"error": str}.
    """
    try:
        from spotify_core.agent.playback_tools import SpotifyPlaybackTools
        with _make_client(user_id) as client:
            tools = SpotifyPlaybackTools(client, DB_PATH, TOKENS_DB, user_id, CLIENT_ID, FERNET_KEY)
            return enrich_auth_error(tools.skip(), user_id)
    except Exception as exc:
        logger.error("skip_track failed: %s", exc)
        return enrich_auth_error({"error": str(exc)}, user_id)


@mcp.tool()
def set_volume(volume_percent: int, user_id: str = DEFAULT_USER_ID) -> dict:
    """Set Spotify playback volume 0–100 (requires Premium).

    Args:
        volume_percent: Target volume 0–100.
        user_id: Spotify user ID. Defaults to SPOTIFY_USER_ID env var.

    Returns:
        {"status": "volume_set", "volume_percent": int} or {"error": str}.
    """
    try:
        from spotify_core.agent.playback_tools import SpotifyPlaybackTools
        with _make_client(user_id) as client:
            tools = SpotifyPlaybackTools(client, DB_PATH, TOKENS_DB, user_id, CLIENT_ID, FERNET_KEY)
            return enrich_auth_error(tools.set_volume(volume_percent), user_id)
    except Exception as exc:
        logger.error("set_volume failed: %s", exc)
        return enrich_auth_error({"error": str(exc)}, user_id)


@mcp.tool()
def add_to_queue(uri: str, user_id: str = DEFAULT_USER_ID) -> dict:
    """Add a Spotify track to the playback queue (requires Premium).

    Args:
        uri: Spotify track URI.
        user_id: Spotify user ID. Defaults to SPOTIFY_USER_ID env var.

    Returns:
        {"status": "queued", "uri": str} or {"error": str}.
    """
    try:
        from spotify_core.agent.playback_tools import SpotifyPlaybackTools
        with _make_client(user_id) as client:
            tools = SpotifyPlaybackTools(client, DB_PATH, TOKENS_DB, user_id, CLIENT_ID, FERNET_KEY)
            return enrich_auth_error(tools.add_to_queue(uri), user_id)
    except Exception as exc:
        logger.error("add_to_queue failed: %s", exc)
        return enrich_auth_error({"error": str(exc)}, user_id)


@mcp.tool()
def create_playlist(
    name: str,
    track_uris: list,
    description: str = "",
    user_id: str = DEFAULT_USER_ID,
) -> dict:
    """Create a new Spotify playlist and populate it with tracks.

    Args:
        name: Playlist name.
        track_uris: List of Spotify track URIs to add.
        description: Optional playlist description.
        user_id: Spotify user ID. Defaults to SPOTIFY_USER_ID env var.

    Returns:
        {"playlist_id": str, "url": str, "track_count": int} or {"error": str}.
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


@mcp.tool()
def remember_preference(key: str, value: str, user_id: str = DEFAULT_USER_ID) -> dict:
    """Store a user preference in long-term memory (persists across conversations).

    Args:
        key: Preference name e.g. "favorite_genre", "preferred_language".
        value: Preference value as a string.
        user_id: Spotify user ID. Defaults to SPOTIFY_USER_ID env var.

    Returns:
        {"status": "saved", "key": str, "value": str}.
    """
    # TODO: can add more structured types later, but for now we can just store everything as strings and let the agent handle parsing/formatting
    from spotify_core.memory import get_store, get_user_namespace
    ns = get_user_namespace(user_id, "preferences")
    with get_store(LTM_DB) as store:
        store.put(ns, key, {"value": value})
    return {"status": "saved", "key": key, "value": value}


@mcp.tool()
def get_memory_summary(user_id: str = DEFAULT_USER_ID) -> dict:
    """Return all stored preferences and facts for a user from long-term memory.

    Args:
        user_id: Spotify user ID. Defaults to SPOTIFY_USER_ID env var.

    Returns:
        {"preferences": dict, "history_facts": dict, "feedback": dict}
    """
    from spotify_core.memory import get_store, get_user_namespace
    summary: dict = {}
    with get_store(LTM_DB) as store:
        for key in ("preferences", "history_facts", "feedback"):
            ns = get_user_namespace(user_id, key)
            items = store.search(ns)
            summary[key] = {item.key: item.value for item in items}
    return summary


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
