"""Data directory resolution for the Python side.

Thin wrapper over :mod:`spotify_core.config_file`, which owns the resolution
rule and must stay in step with ``apps/tauri/src-tauri/src/config.rs``:

    $SPOTIFY_CONFIG set -> that file, data beside it in ./data
    otherwise           -> platformdirs (where a packaged install lives)

`SPOTIFY_DATA_DIR` overrides both, as an escape hatch for CI.
"""
from pathlib import Path

from spotify_core import config_file


def data_dir() -> Path:
    return config_file.data_dir()


def history_db() -> Path:
    return (data_dir() / "history.db").resolve()
