"""Config helpers for the dashboard: sync credentials and LLM provider choices.

SPOTIFY_CLIENT_ID and TOKEN_ENCRYPT_KEY are read from the environment (after
loading the platformdirs .env); DB paths and user id come from settings.
"""
import os

from spotify_core.env import ensure_dotenv_loaded, get_client_id, get_fernet_key

ensure_dotenv_loaded()
from spotify_core.config import settings

# LLM models offered by the AI report block, per provider. v1 ships Google only.
_GOOGLE_MODELS = ["gemini-2.5-flash", "gemini-2.5-pro"]


def get_sync_args() -> dict:
    """Return the keyword arguments for spotify_core.db.pipeline.sync_api_to_db."""
    return {
        "db_path": str(settings.history_db_path),
        "tokens_db_path": str(settings.tokens_db_path),
        "user_id": settings.spotify_user_id,
        "client_id": get_client_id(),
        "fernet_key": get_fernet_key(),
    }


def get_llm_config() -> dict:
    """Return the LLM choices available to the AI report block.

    Inspects the environment for provider API keys. In v1 only GEMINI_API_KEY
    yields usable models.

    Returns:
        {"models": [{"provider": str, "model": str}, ...],
         "default": {"provider": str, "model": str} | None}
    """
    models: list[dict] = []
    if os.getenv("GEMINI_API_KEY"):
        models = [{"provider": "google", "model": m} for m in _GOOGLE_MODELS]
    return {"models": models, "default": models[0] if models else None}
