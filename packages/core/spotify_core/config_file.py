"""Reading the JSON config file that the desktop app owns.

The Rust side (`apps/tauri/src-tauri/src/config.rs`) is the writer and the
authority on where this file lives; this module is the Python *reader*, and the
two must agree on both the path rule and the flat `{"KEY": "value"}` shape.

Path rule, identical to config.rs:

    $SPOTIFY_CONFIG set -> that path
    otherwise           -> <platformdirs user_config_dir("spotify-mcp")>/config.json

Writes are deliberately *not* implemented here: the app writes config, Python
reads it.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import platformdirs

_APP_NAME = "spotify-mcp"
_CONFIG_FILE = "config.json"


def path() -> Path:
    """The active config file. See the module docstring for the rule."""
    raw = os.environ.get("SPOTIFY_CONFIG", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path(platformdirs.user_config_dir(_APP_NAME)) / _CONFIG_FILE).resolve()


def read() -> dict[str, str]:
    """The whole config as a dict. Missing or corrupt file reads as empty.

    A corrupt file must not be fatal: "nothing configured" is a state every
    caller already handles, an unhandled JSONDecodeError is not.
    """
    try:
        data = json.loads(path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items() if v is not None}


def load_into_env() -> None:
    """Copy config values into ``os.environ`` without overriding what is there.

    For SDKs that read their own credentials straight from the environment
    (Langfuse, LangSmith, OpenAI). A real environment variable always wins, so
    a shell can still override any single key.
    """
    for key, value in read().items():
        os.environ.setdefault(key, value)


def data_dir() -> Path:
    """Where ``history.db`` lives. Mirrors ``data_dir()`` in config.rs.

    A dev config keeps its data beside itself, so a checkout never reads or
    writes the database a packaged install is using.
    """
    raw = os.environ.get("SPOTIFY_DATA_DIR", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    if os.environ.get("SPOTIFY_CONFIG", "").strip():
        return (path().parent / "data").resolve()
    return Path(platformdirs.user_data_dir(_APP_NAME)).resolve()
