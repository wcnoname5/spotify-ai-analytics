"""Sync-credential resolution for the dashboard's Sync button.

SPOTIFY_CLIENT_ID and TOKEN_ENCRYPT_KEY are read from the environment (after
loading the platformdirs .env), while DB paths and user id come from settings.
"""
from spotify_core.env import ensure_dotenv_loaded, get_client_id, get_fernet_key

ensure_dotenv_loaded()
from spotify_core.config import settings


def get_sync_args() -> dict:
    """Return the keyword arguments for spotify_core.db.pipeline.sync_api_to_db."""
    return {
        "db_path": str(settings.history_db_path),
        "tokens_db_path": str(settings.tokens_db_path),
        "user_id": settings.spotify_user_id,
        "client_id": get_client_id(),
        "fernet_key": get_fernet_key(),
    }
