"""Spotify AI Analytics MCP Server — development entry point.

For PyPI-installed users the server is launched via `spotify-mcp serve`.
This file exists as a convenience for checkout-mode development:

    uv run python apps/mcp/server.py

Required environment variables:
    SPOTIFY_CLIENT_ID   — Spotify app client ID
    TOKEN_ENCRYPT_KEY   — Fernet key bytes (base64-encoded) for token encryption
"""
import os

from dotenv import load_dotenv
from loguru import logger

from spotify_core import paths
from spotify_core.logging import setup_mcp_logging
from spotify_mcp.config import get_client_id, get_fernet_key

# Load platformdirs .env first; cwd .env fills any gaps but never overrides.
if paths.env_file().exists():
    load_dotenv(paths.env_file())
load_dotenv(override=False)

_log_file = setup_mcp_logging(level=os.getenv("LOG_LEVEL", "DEBUG").upper())
logger.info("Logging to {}", _log_file)

if not get_client_id():
    logger.warning("SPOTIFY_CLIENT_ID is not set. Set it in .env or as an environment variable.")
if not get_fernet_key():
    logger.warning(
        "TOKEN_ENCRYPT_KEY is not set. "
        'Generate one with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
    )

from spotify_mcp._mcp import main, mcp  # noqa: E402 — must come after env/logging setup

__all__ = ["main", "mcp"]

if __name__ == "__main__":
    main()
