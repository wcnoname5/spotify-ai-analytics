"""Shared MCP server config: paths, env, helpers used by every tool module."""
import logging
import os

from dotenv import load_dotenv

load_dotenv()

from spotify_core.config import settings

logger = logging.getLogger(__name__)

CLIENT_ID: str = os.getenv("SPOTIFY_CLIENT_ID", "")
_raw_key = os.getenv("TOKEN_ENCRYPT_KEY", "")
FERNET_KEY: bytes = _raw_key.encode() if _raw_key else b""

DB_PATH: str = str(settings.history_db_path)
TOKENS_DB: str = str(settings.tokens_db_path)
LTM_DB: str = str(settings.ltm_db_path)
DEFAULT_USER_ID: str = settings.spotify_user_id

EMPTY_DB_RESPONSE: dict = {
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

# Tools removed from registration when the connected account is not Premium.
PREMIUM_TOOLS = ["play_track", "pause_playback", "skip_track", "set_volume", "add_to_queue"]


def make_client(user_id: str):
    """Build a SpotifyClient for the given user against the configured tokens DB."""
    from spotify_core.spotify_client.client import SpotifyClient
    return SpotifyClient(TOKENS_DB, user_id, CLIENT_ID, FERNET_KEY)
