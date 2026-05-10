"""Tests for spotify_core.paths — config/data dir resolution."""
import os
from pathlib import Path

import pytest

from spotify_core import paths


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("SPOTIFY_MCP_DATA_DIR", raising=False)
    monkeypatch.delenv("SPOTIFY_MCP_CONFIG_DIR", raising=False)
    monkeypatch.delenv("SPOTIFY_DATA_PATH", raising=False)
    monkeypatch.delenv("HISTORY_DB_PATH", raising=False)
    monkeypatch.delenv("TOKENS_DB_PATH", raising=False)
    monkeypatch.delenv("LTM_DB_PATH", raising=False)
    monkeypatch.delenv("CHECKPOINTS_DB_PATH", raising=False)


def test_data_dir_uses_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("SPOTIFY_MCP_DATA_DIR", str(tmp_path))
    assert paths.data_dir() == tmp_path.resolve()


def test_config_dir_uses_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("SPOTIFY_MCP_CONFIG_DIR", str(tmp_path))
    assert paths.config_dir() == tmp_path.resolve()


def test_data_dir_default_is_platformdirs(monkeypatch):
    import platformdirs
    expected = Path(platformdirs.user_data_dir("spotify-mcp")).resolve()
    assert paths.data_dir() == expected


def test_config_dir_default_is_platformdirs(monkeypatch):
    import platformdirs
    expected = Path(platformdirs.user_config_dir("spotify-mcp")).resolve()
    assert paths.config_dir() == expected


def test_env_file_path_lives_under_config_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("SPOTIFY_MCP_CONFIG_DIR", str(tmp_path))
    assert paths.env_file() == (tmp_path / ".env").resolve()


def test_db_paths_live_under_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("SPOTIFY_MCP_DATA_DIR", str(tmp_path))
    assert paths.history_db() == (tmp_path / "history.db").resolve()
    assert paths.tokens_db() == (tmp_path / "tokens.db").resolve()
    assert paths.ltm_db() == (tmp_path / "ltm.db").resolve()
    assert paths.checkpoints_db() == (tmp_path / "checkpoints.db").resolve()
    assert paths.spotify_history_dir() == (tmp_path / "spotify_history").resolve()


def test_ensure_dirs_creates_missing(monkeypatch, tmp_path):
    cfg = tmp_path / "cfg"
    data = tmp_path / "data"
    monkeypatch.setenv("SPOTIFY_MCP_CONFIG_DIR", str(cfg))
    monkeypatch.setenv("SPOTIFY_MCP_DATA_DIR", str(data))
    paths.ensure_dirs()
    assert cfg.is_dir()
    assert data.is_dir()


def test_settings_picks_up_data_dir_override(monkeypatch, tmp_path):
    monkeypatch.setenv("SPOTIFY_MCP_DATA_DIR", str(tmp_path))
    # Force re-import so module-level `settings` re-resolves
    import importlib

    import spotify_core.config as cfg
    importlib.reload(cfg)

    assert cfg.settings.history_db_path == (tmp_path / "history.db").resolve()
    assert cfg.settings.tokens_db_path == (tmp_path / "tokens.db").resolve()
    assert cfg.settings.ltm_db_path == (tmp_path / "ltm.db").resolve()
    assert cfg.settings.spotify_data_path == (tmp_path / "spotify_history").resolve()
