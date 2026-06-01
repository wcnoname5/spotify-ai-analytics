"""Config helpers for the dashboard: sync credentials and LLM provider choices.

All config (credentials, LLM keys, DB paths, user ID) is read from settings.
"""
from spotify_core.config import get_client_id, get_fernet_key, settings

# LLM models offered by the AI report block, per provider.
_GOOGLE_MODELS = ["gemini-2.5-flash", "gemini-2.5-flash-lite"]
_OPENAI_MODELS = ["gpt-5.4-mini", "gpt-5.4"]


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

    Inspects settings for provider API keys. In v1 only gemini_api_key
    yields usable models.

    Returns:
        {"models": [{"provider": str, "model": str}, ...],
         "default": {"provider": str, "model": str} | None}
    """
    models: list[dict] = []
    if settings.gemini_api_key:
        models += [{"provider": "google", "model": m} for m in _GOOGLE_MODELS]
    if settings.openai_api_key:
        models += [{"provider": "openai", "model": m} for m in _OPENAI_MODELS]
    return {"models": models}
