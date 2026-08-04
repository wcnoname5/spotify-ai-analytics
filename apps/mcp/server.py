"""Spotify AI Analytics MCP Server — development entry point.

This file exists as a convenience for checkout-mode development:

    uv run python apps/mcp/server.py

Required environment variables:
    SPOTIFY_CLIENT_ID   — Spotify app client ID
    TOKEN_ENCRYPT_KEY   — Fernet key bytes (base64-encoded) for token encryption
"""
import os

from loguru import logger

from spotify_core import config_file
from spotify_core.logging import setup_mcp_logging
from spotify_mcp.config import get_client_id, get_fernet_key

# Copy config.json into os.environ for env-based SDKs. Real environment variables
# always win, so a shell can override any single key. Set $SPOTIFY_CONFIG to point
# at a dev config instead of the one a packaged install uses.
config_file.load_into_env()

_log_file = setup_mcp_logging(level=os.getenv("LOG_LEVEL", "DEBUG").upper())
logger.info("Logging to {}", _log_file)

if not get_client_id():
    raise RuntimeError(
        f"SPOTIFY_CLIENT_ID is not set in {config_file.path()} — set it in the desktop app's Setup page."
    )
if not get_fernet_key():
    raise RuntimeError(
        f"TOKEN_ENCRYPT_KEY is not set in {config_file.path()} — open the desktop app once; it generates one."
    )

from spotify_mcp._mcp import main, mcp  # noqa: E402 — must come after env/logging setup

__all__ = ["main", "mcp"]

if __name__ == "__main__":
    main()
