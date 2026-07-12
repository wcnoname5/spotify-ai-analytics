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


def platform_env_file() -> Path:
    """The platformdirs .env location, regardless of the active resolution mode."""
    return (Path(platformdirs.user_config_dir(_APP_NAME)) / ".env").resolve()


def cwd_env_file() -> Path:
    """The checkout/cwd .env location, regardless of the active resolution mode."""
    return (Path.cwd() / ".env").resolve()


def resolution_source(env_var: str) -> str:
    """Which rule decided a directory: 'env' (explicit override), 'dev', or 'platformdirs'."""
    if os.environ.get(env_var):
        return "env"
    if is_dev():
        return "dev"
    return "platformdirs"


def describe() -> dict:
    """Snapshot of the resolved paths and how each was chosen.

    Consumed by `spotify-mcp doctor` / `spotify-mcp path` so users can see
    which .env and which DBs a given invocation is actually using.
    """
    return {
        "dev": is_dev(),
        "config_dir": str(config_dir()),
        "config_dir_source": resolution_source("SPOTIFY_MCP_CONFIG_DIR"),
        "data_dir": str(data_dir()),
        "data_dir_source": resolution_source("SPOTIFY_MCP_DATA_DIR"),
        "env_file": str(env_file()),
        "env_file_exists": env_file().exists(),
        "history_db": str(history_db()),
        "history_db_exists": history_db().exists(),
        "tokens_db": str(tokens_db()),
        "tokens_db_exists": tokens_db().exists(),
    }
