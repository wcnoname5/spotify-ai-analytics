"""Config and data directory resolution for the Python side.

Thin wrapper over :mod:`spotify_core.config_file`, which owns the resolution
rule and must stay in step with ``apps/tauri/src-tauri/src/config.rs``:

    $SPOTIFY_CONFIG set -> that file, data beside it in ./data
    otherwise           -> platformdirs (where a packaged install lives)

The previous version had a third mode: ``DEV=true`` read out of ``Path.cwd()/.env``,
which made the answer depend on the directory a process was launched from. That
is gone deliberately — it is the reason the same key could be live in two files
at once. `SPOTIFY_DATA_DIR` remains as an escape hatch for CI.
"""
from pathlib import Path

from spotify_core import config_file


def config_dir() -> Path:
    return config_file.path().parent


def data_dir() -> Path:
    return config_file.data_dir()


def config_path() -> Path:
    """The config.json this invocation reads."""
    return config_file.path()


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


# --------------------------------------------------------------------------
# Transitional shims. DO NOT add callers.
#
# `wizard/`, `cloud.py` and `wizard/state.py` still read and write a `.env`.
# They are all deleted once the GUI owns setup (OAuth, history import, deploy),
# and these three functions go with them. They exist only so the tree stays
# green in between — the app itself no longer reaches any of this.
#
# While both formats exist, config.json is the one the app reads. A value the
# wizard writes to .env is therefore invisible to the desktop app.
# --------------------------------------------------------------------------

def env_file() -> Path:
    return (config_dir() / ".env").resolve()


def is_dev() -> bool:
    import os

    return bool(os.environ.get("SPOTIFY_CONFIG", "").strip())


def platform_env_file() -> Path:
    import platformdirs

    return (Path(platformdirs.user_config_dir("spotify-mcp")) / ".env").resolve()


def cwd_env_file() -> Path:
    return (Path.cwd() / ".env").resolve()


def describe() -> dict:
    """Snapshot of the resolved paths, so a user can see which files an
    invocation is actually using."""
    return {
        "config_path": str(config_path()),
        "config_exists": config_path().exists(),
        "config_dir": str(config_dir()),
        "data_dir": str(data_dir()),
        "history_db": str(history_db()),
        "history_db_exists": history_db().exists(),
        "tokens_db": str(tokens_db()),
        "tokens_db_exists": tokens_db().exists(),
    }
