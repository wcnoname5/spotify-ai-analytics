"""Shared env helpers — thin wrappers over Settings.

These functions read from `spotify_core.config.settings`, which loads the
platform-resolved `.env` via pydantic-settings. Entry points that need the
`.env` values in `os.environ` for third-party SDKs (e.g. Langfuse) call
`dotenv.load_dotenv(paths.env_file())` themselves (see `apps/mcp/server.py`
and the dashboard entry `main_page.py`).
"""
from __future__ import annotations


def get_client_id() -> str:
    """Return SPOTIFY_CLIENT_ID from Settings."""
    from spotify_core.config import settings
    return settings.spotify_client_id


def get_fernet_key() -> bytes:
    """Return TOKEN_ENCRYPT_KEY as bytes from Settings."""
    from spotify_core.config import settings
    return settings.fernet_key_bytes
