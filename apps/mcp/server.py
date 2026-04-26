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

mcp = FastMCP("spotify-analytics")

# ------------------------------------------------------------------
# History sync tools
# ------------------------------------------------------------------


@mcp.tool()
def sync_history(user_id: str = DEFAULT_USER_ID) -> dict:
    """Fetch the 50 most recent Spotify plays and store them in the local DB.

    Args:
        user_id: Spotify user ID whose history to sync. Defaults to SPOTIFY_USER_ID env var.

    Returns:
        {"inserted": int, "cursor_ms": int}
    """
    from spotify_core.db.pipeline import sync_api_to_db
    return sync_api_to_db(
        db_path=DB_PATH,
        tokens_db_path=TOKENS_DB,
        user_id=user_id,
        client_id=CLIENT_ID,
        fernet_key=FERNET_KEY,
    )


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
    """
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
    """
    from spotify_core.db.queries import get_top_tracks as _get_top_tracks
    return _get_top_tracks(DB_PATH, limit=limit, start_date=start_date, end_date=end_date)


@mcp.tool()
def get_listening_summary() -> dict:
    """Return a summary of local listening history (total plays, date range, unique artists/tracks).
    Note: played_at is in ISO format in UTC time, so it may not matches current time zone.
    Returns:
        {
            "total_plays": int,
            "unique_tracks": int,
            "unique_artists": int,
            "earliest_played_at": str | None,
            "latest_played_at": str | None,
        }
    """
    from spotify_core.db.queries import get_listening_summary as _summary
    return _summary(DB_PATH)


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
    from spotify_core.agent.playback_tools import SpotifyPlaybackTools
    with _make_client(user_id) as client:
        tools = SpotifyPlaybackTools(client, DB_PATH, TOKENS_DB, user_id, CLIENT_ID, FERNET_KEY)
        return tools.get_now_playing()


@mcp.tool()
def play_track(uri: str, user_id: str = DEFAULT_USER_ID) -> dict:
    """Start playing a Spotify track (requires Premium).

    Args:
        uri: Spotify track URI e.g. "spotify:track:4iV5W9uYEdYUVa79Axb7Rh".
        user_id: Spotify user ID. Defaults to SPOTIFY_USER_ID env var.

    Returns:
        {"status": "playing", "uri": str} or {"error": str}.
    """
    from spotify_core.agent.playback_tools import SpotifyPlaybackTools
    with _make_client(user_id) as client:
        tools = SpotifyPlaybackTools(client, DB_PATH, TOKENS_DB, user_id, CLIENT_ID, FERNET_KEY)
        return tools.play_track(uri)


@mcp.tool()
def pause_playback(user_id: str = DEFAULT_USER_ID) -> dict:
    """Pause the current Spotify playback (requires Premium).

    Args:
        user_id: Spotify user ID. Defaults to SPOTIFY_USER_ID env var.

    Returns:
        {"status": "paused"} or {"error": str}.
    """
    from spotify_core.agent.playback_tools import SpotifyPlaybackTools
    with _make_client(user_id) as client:
        tools = SpotifyPlaybackTools(client, DB_PATH, TOKENS_DB, user_id, CLIENT_ID, FERNET_KEY)
        return tools.pause()


@mcp.tool()
def skip_track(user_id: str = DEFAULT_USER_ID) -> dict:
    """Skip to the next Spotify track (requires Premium).

    Args:
        user_id: Spotify user ID. Defaults to SPOTIFY_USER_ID env var.

    Returns:
        {"status": "skipped"} or {"error": str}.
    """
    from spotify_core.agent.playback_tools import SpotifyPlaybackTools
    with _make_client(user_id) as client:
        tools = SpotifyPlaybackTools(client, DB_PATH, TOKENS_DB, user_id, CLIENT_ID, FERNET_KEY)
        return tools.skip()


@mcp.tool()
def set_volume(volume_percent: int, user_id: str = DEFAULT_USER_ID) -> dict:
    """Set Spotify playback volume 0–100 (requires Premium).

    Args:
        volume_percent: Target volume 0–100.
        user_id: Spotify user ID. Defaults to SPOTIFY_USER_ID env var.

    Returns:
        {"status": "volume_set", "volume_percent": int} or {"error": str}.
    """
    from spotify_core.agent.playback_tools import SpotifyPlaybackTools
    with _make_client(user_id) as client:
        tools = SpotifyPlaybackTools(client, DB_PATH, TOKENS_DB, user_id, CLIENT_ID, FERNET_KEY)
        return tools.set_volume(volume_percent)


@mcp.tool()
def add_to_queue(uri: str, user_id: str = DEFAULT_USER_ID) -> dict:
    """Add a Spotify track to the playback queue (requires Premium).

    Args:
        uri: Spotify track URI.
        user_id: Spotify user ID. Defaults to SPOTIFY_USER_ID env var.

    Returns:
        {"status": "queued", "uri": str} or {"error": str}.
    """
    from spotify_core.agent.playback_tools import SpotifyPlaybackTools
    with _make_client(user_id) as client:
        tools = SpotifyPlaybackTools(client, DB_PATH, TOKENS_DB, user_id, CLIENT_ID, FERNET_KEY)
        return tools.add_to_queue(uri)


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
    from spotify_core.agent.playback_tools import SpotifyPlaybackTools
    with _make_client(user_id) as client:
        tools = SpotifyPlaybackTools(client, DB_PATH, TOKENS_DB, user_id, CLIENT_ID, FERNET_KEY)
        return tools.create_playlist(name, track_uris, description)


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
