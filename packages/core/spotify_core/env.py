"""Shared env helpers — thin wrappers over Settings for backward compatibility.

Historically these functions called `os.getenv()` directly. They now read from
`spotify_core.config.settings`, which loads the platform-resolved `.env` via
pydantic-settings. Callers that import `get_client_id` / `get_fernet_key`
need not change.
"""
from __future__ import annotations


def ensure_dotenv_loaded() -> None:
    """No-op retained for backward compatibility.

    `Settings` loads `paths.env_file()` at import time via pydantic-settings.
    """
    return None


def get_client_id() -> str:
    """Return SPOTIFY_CLIENT_ID from Settings."""
    from spotify_core.config import settings
    return settings.spotify_client_id


def get_fernet_key() -> bytes:
    """Return TOKEN_ENCRYPT_KEY as bytes from Settings."""
    from spotify_core.config import settings
    return settings.fernet_key_bytes
