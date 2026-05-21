"""Sync-credential resolution for the dashboard's Sync button.

Mirrors apps/mcp/spotify_mcp/config.py: SPOTIFY_CLIENT_ID and TOKEN_ENCRYPT_KEY
are read from the environment (after loading the platformdirs .env), while the
DB paths and user id come from spotify_core.config.settings.
"""
import os

from dotenv import load_dotenv

from spotify_core import paths

# Platformdirs .env wins; a cwd .env is a dev-convenience fallback only.
if paths.env_file().exists():
    load_dotenv(paths.env_file())
load_dotenv(override=False)

# Imported after load_dotenv so settings sees the platformdirs .env, matching
# apps/mcp/spotify_mcp/config.py.
from spotify_core.config import settings


def get_client_id() -> str:
    """Read SPOTIFY_CLIENT_ID from the environment at call time."""
    return os.getenv("SPOTIFY_CLIENT_ID", "")


def get_fernet_key() -> bytes:
    """Read TOKEN_ENCRYPT_KEY from the environment at call time, as bytes."""
    raw = os.getenv("TOKEN_ENCRYPT_KEY", "")
    return raw.encode() if raw else b""


def get_sync_args() -> dict:
    """Return the keyword arguments for spotify_core.db.pipeline.sync_api_to_db."""
    return {
        "db_path": str(settings.history_db_path),
        "tokens_db_path": str(settings.tokens_db_path),
        "user_id": settings.spotify_user_id,
        "client_id": get_client_id(),
        "fernet_key": get_fernet_key(),
    }
