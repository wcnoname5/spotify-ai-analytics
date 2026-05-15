"""Single source of truth for spotify-mcp config and data directory resolution.

Resolution priority (both config_dir and data_dir):
    1. Explicit env var (SPOTIFY_MCP_CONFIG_DIR / SPOTIFY_MCP_DATA_DIR)
    2. platformdirs default (user_config_dir / user_data_dir, app name "spotify-mcp")

Checkout-mode developers opt in by setting the env vars in their shell profile
(e.g. SPOTIFY_MCP_DATA_DIR=$PWD/data, SPOTIFY_MCP_CONFIG_DIR=$PWD).
"""
import os
from pathlib import Path

import platformdirs

_APP_NAME = "spotify-mcp"


def config_dir() -> Path:
    raw = os.environ.get("SPOTIFY_MCP_CONFIG_DIR")
    if raw:
        return Path(raw).expanduser().resolve()
    return Path(platformdirs.user_config_dir(_APP_NAME)).resolve()


def data_dir() -> Path:
    raw = os.environ.get("SPOTIFY_MCP_DATA_DIR")
    if raw:
        return Path(raw).expanduser().resolve()
    return Path(platformdirs.user_data_dir(_APP_NAME)).resolve()


def env_file() -> Path:
    return (config_dir() / ".env").resolve()


def history_db() -> Path:
    return (data_dir() / "history.db").resolve()


def tokens_db() -> Path:
    return (data_dir() / "tokens.db").resolve()


def ltm_db() -> Path:
    return (data_dir() / "ltm.db").resolve()


def checkpoints_db() -> Path:
    return (data_dir() / "checkpoints.db").resolve()


def spotify_history_dir() -> Path:
    return (data_dir() / "spotify_history").resolve()


def ensure_dirs() -> None:
    """Idempotently create config_dir() and data_dir()."""
    config_dir().mkdir(parents=True, exist_ok=True)
    data_dir().mkdir(parents=True, exist_ok=True)
