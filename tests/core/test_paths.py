"""Tests for spotify_core.paths / config_file — config and data resolution.

The rule under test (see config_file's docstring):

    $SPOTIFY_CONFIG set -> that file, data beside it in ./data
    otherwise           -> platformdirs
"""
import os
from pathlib import Path

import pytest

from spotify_core import config_file, paths


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    # load_into_env() writes to os.environ; give each test its own copy.
    monkeypatch.setattr(os, "environ", dict(os.environ))
    for key in ("SPOTIFY_CONFIG", "SPOTIFY_DATA_DIR", "HISTORY_DB_PATH"):
        monkeypatch.delenv(key, raising=False)


def test_config_path_default_is_platformdirs():
    import platformdirs

    expected = (Path(platformdirs.user_config_dir("spotify-mcp")) / "config.json").resolve()
    assert config_file.path() == expected


def test_data_dir_default_is_platformdirs():
    import platformdirs

    assert paths.data_dir() == Path(platformdirs.user_data_dir("spotify-mcp")).resolve()


def test_spotify_config_selects_the_file(monkeypatch, tmp_path):
    target = tmp_path / "dev.config.json"
    monkeypatch.setenv("SPOTIFY_CONFIG", str(target))
    assert config_file.path() == target.resolve()


def test_a_dev_config_keeps_its_data_beside_itself(monkeypatch, tmp_path):
    """The isolation the whole rule exists for: a checkout must not read or
    write the database a packaged install is using."""
    monkeypatch.setenv("SPOTIFY_CONFIG", str(tmp_path / "dev.config.json"))
    assert paths.data_dir() == (tmp_path / "data").resolve()
    assert paths.history_db() == (tmp_path / "data" / "history.db").resolve()


def test_data_dir_override_wins(monkeypatch, tmp_path):
    """SPOTIFY_DATA_DIR stays as an escape hatch for CI."""
    monkeypatch.setenv("SPOTIFY_CONFIG", str(tmp_path / "dev.config.json"))
    monkeypatch.setenv("SPOTIFY_DATA_DIR", str(tmp_path / "elsewhere"))
    assert paths.data_dir() == (tmp_path / "elsewhere").resolve()


def test_read_returns_empty_when_the_file_is_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("SPOTIFY_CONFIG", str(tmp_path / "absent.json"))
    assert config_file.read() == {}


def test_corrupt_config_reads_as_empty_rather_than_raising(monkeypatch, tmp_path):
    target = tmp_path / "corrupt.json"
    target.write_text("{ not json", encoding="utf-8")
    monkeypatch.setenv("SPOTIFY_CONFIG", str(target))
    assert config_file.read() == {}


def test_load_into_env_does_not_override_real_env_vars(monkeypatch, tmp_path):
    target = tmp_path / "config.json"
    target.write_text('{"GEMINI_API_KEY": "from_file", "OPENAI_API_KEY": "k"}', encoding="utf-8")
    monkeypatch.setenv("SPOTIFY_CONFIG", str(target))
    monkeypatch.setenv("GEMINI_API_KEY", "from_shell")
    config_file.load_into_env()

    assert os.environ["GEMINI_API_KEY"] == "from_shell"
    assert os.environ["OPENAI_API_KEY"] == "k"


def test_settings_picks_up_the_config_file(monkeypatch, tmp_path):
    target = tmp_path / "config.json"
    target.write_text('{"GEMINI_MODEL": "from-file", "HISTORY_DB_PATH": "sub/h.db"}', encoding="utf-8")
    monkeypatch.setenv("SPOTIFY_CONFIG", str(target))
    monkeypatch.setenv("SPOTIFY_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("GEMINI_MODEL", raising=False)

    from spotify_core.config import Settings

    config_file.load_into_env()
    settings = Settings()
    assert settings.gemini_model == "from-file"
    # Relative paths resolve against the data dir, not the cwd.
    assert settings.history_db_path == (tmp_path / "sub" / "h.db").resolve()
