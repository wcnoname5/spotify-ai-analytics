"""Shared MCP server config: paths, env, helpers used by every tool module."""
from loguru import logger
from spotify_core.config import settings
from spotify_core.env import get_client_id, get_fernet_key


DB_PATH: str = str(settings.history_db_path)
TOKENS_DB: str = str(settings.tokens_db_path)
LTM_DB: str = str(settings.ltm_db_path)
DEFAULT_USER_ID: str = settings.spotify_user_id

EMPTY_DB_RESPONSE: dict = {
    "warning": "No listening history in the local database.",
}

# Tools removed from registration when the connected account is not Premium.
PREMIUM_TOOLS = ["play_track", "pause_playback", "skip_track", "set_volume", "add_to_queue"]


def make_client(user_id: str):
    """Build a SpotifyClient for the given user against the configured tokens DB."""
    from spotify_core.spotify_client.client import SpotifyClient
    return SpotifyClient(TOKENS_DB, user_id, get_client_id(), get_fernet_key())
