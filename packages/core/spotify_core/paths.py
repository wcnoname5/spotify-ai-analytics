"""Single source of truth for spotify-mcp config and data directory resolution.

Resolution priority (both config_dir and data_dir):
    1. Explicit env var (SPOTIFY_MCP_CONFIG_DIR / SPOTIFY_MCP_DATA_DIR)
    2. DEV=true (process env or cwd .env) → repo checkout: config_dir=cwd, data_dir=cwd/data
    3. platformdirs default (user_config_dir / user_data_dir, app name "spotify-mcp")

Checkout-mode developers set DEV=true in the repo .env (or shell); the explicit
SPOTIFY_MCP_* env vars still win when both are set.
"""
import os
from pathlib import Path

import platformdirs

_APP_NAME = "spotify-mcp"
_TRUTHY = ("1", "true", "yes", "on")


def is_dev() -> bool:
    """True when DEV is set truthy in the process env or the cwd .env file."""
    raw = os.environ.get("DEV")
    if raw is None:
        from spotify_core import env_file as _env_file

        raw = _env_file.read_key(Path.cwd() / ".env", "DEV")
    return str(raw).strip().lower() in _TRUTHY


def config_dir() -> Path:
    raw = os.environ.get("SPOTIFY_MCP_CONFIG_DIR")
    if raw:
        return Path(raw).expanduser().resolve()
    if is_dev():
        return Path.cwd().resolve()
    return Path(platformdirs.user_config_dir(_APP_NAME)).resolve()


def data_dir() -> Path:
    raw = os.environ.get("SPOTIFY_MCP_DATA_DIR")
    if raw:
        return Path(raw).expanduser().resolve()
    if is_dev():
        return (Path.cwd() / "data").resolve()
    return Path(platformdirs.user_data_dir(_APP_NAME)).resolve()


def env_file() -> Path:
    return (config_dir() / ".env").resolve()


def history_db() -> Path:
    return (data_dir() / "history.db").resolve()


def tokens_db() -> Path:
    return (data_dir() / "tokens.db").resolve()


def spotify_history_dir() -> Path:
    return (data_dir() / "spotify_history").resolve()


def ensure_dirs() -> None:
    """Idempotently create config_dir() and data_dir()."""
    config_dir().mkdir(parents=True, exist_ok=True)
    data_dir().mkdir(parents=True, exist_ok=True)
