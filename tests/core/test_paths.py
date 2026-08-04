"""Tests for spotify_core.paths / config_file — config and data resolution.

The rule under test is deliberately narrow (see config_file's docstring):

    $SPOTIFY_CONFIG set -> that file, data beside it in ./data
    otherwise           -> platformdirs

It replaced a three-mode rule whose middle mode (`DEV=true`) was read from
``Path.cwd()/.env``, so the answer depended on the launch directory. The tests
for that mode are gone with it — the point of the change is that the condition
cannot be expressed any more.
"""
from pathlib import Path

import pytest

from spotify_core import config_file, paths


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in (
        "SPOTIFY_CONFIG",
        "SPOTIFY_DATA_DIR",
        "SPOTIFY_DATA_PATH",
        "HISTORY_DB_PATH",
        "TOKENS_DB_PATH",
    ):
        monkeypatch.delenv(key, raising=False)


def test_config_path_default_is_platformdirs():
    import platformdirs

    expected = (Path(platformdirs.user_config_dir("spotify-mcp")) / "config.json").resolve()
    assert paths.config_path() == expected


def test_data_dir_default_is_platformdirs():
    import platformdirs

    assert paths.data_dir() == Path(platformdirs.user_data_dir("spotify-mcp")).resolve()


def test_spotify_config_selects_the_file(monkeypatch, tmp_path):
    target = tmp_path / "dev.config.json"
    monkeypatch.setenv("SPOTIFY_CONFIG", str(target))
    assert paths.config_path() == target.resolve()
    assert paths.config_dir() == tmp_path.resolve()


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


def test_db_paths_live_under_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("SPOTIFY_DATA_DIR", str(tmp_path))
    assert paths.history_db() == (tmp_path / "history.db").resolve()
    assert paths.tokens_db() == (tmp_path / "tokens.db").resolve()
    assert paths.spotify_history_dir() == (tmp_path / "spotify_history").resolve()


def test_ensure_dirs_creates_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("SPOTIFY_CONFIG", str(tmp_path / "cfg" / "config.json"))
    monkeypatch.setenv("SPOTIFY_DATA_DIR", str(tmp_path / "data"))
    paths.ensure_dirs()
    assert (tmp_path / "cfg").is_dir()
    assert (tmp_path / "data").is_dir()


def test_read_returns_empty_when_the_file_is_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("SPOTIFY_CONFIG", str(tmp_path / "absent.json"))
    assert config_file.read() == {}
    assert config_file.read_key("SPOTIFY_CLIENT_ID") is None


def test_corrupt_config_reads_as_empty_rather_than_raising(monkeypatch, tmp_path):
    target = tmp_path / "corrupt.json"
    target.write_text("{ not json", encoding="utf-8")
    monkeypatch.setenv("SPOTIFY_CONFIG", str(target))
    assert config_file.read() == {}


def test_read_key_prefers_the_process_env(monkeypatch, tmp_path):
    target = tmp_path / "config.json"
    target.write_text('{"SPOTIFY_CLIENT_ID": "from_file"}', encoding="utf-8")
    monkeypatch.setenv("SPOTIFY_CONFIG", str(target))
    assert config_file.read_key("SPOTIFY_CLIENT_ID") == "from_file"
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "from_env")
    assert config_file.read_key("SPOTIFY_CLIENT_ID") == "from_env"


def test_upsert_leaves_sibling_keys_alone(monkeypatch, tmp_path):
    target = tmp_path / "config.json"
    target.write_text('{"KEEP_ME": "untouched"}', encoding="utf-8")
    monkeypatch.setenv("SPOTIFY_CONFIG", str(target))
    config_file.upsert("SPOTIFY_USER_ID", "someone")
    assert config_file.read() == {"KEEP_ME": "untouched", "SPOTIFY_USER_ID": "someone"}


def test_load_into_env_does_not_override_real_env_vars(monkeypatch, tmp_path):
    target = tmp_path / "config.json"
    target.write_text('{"GEMINI_API_KEY": "from_file", "OPENAI_API_KEY": "k"}', encoding="utf-8")
    monkeypatch.setenv("SPOTIFY_CONFIG", str(target))
    monkeypatch.setenv("GEMINI_API_KEY", "from_shell")
    config_file.load_into_env()
    import os

    assert os.environ["GEMINI_API_KEY"] == "from_shell"
    assert os.environ["OPENAI_API_KEY"] == "k"


def test_settings_picks_up_the_config_file(monkeypatch, tmp_path):
    target = tmp_path / "config.json"
    target.write_text('{"SPOTIFY_CLIENT_ID": "abc123"}', encoding="utf-8")
    monkeypatch.setenv("SPOTIFY_CONFIG", str(target))
    monkeypatch.setenv("SPOTIFY_DATA_DIR", str(tmp_path))

    from spotify_core import config as cfg

    # load() rebuilds from the current file; the module-level `settings` was
    # resolved at import time and cannot see this.
    settings = cfg.load()
    assert settings.spotify_client_id == "abc123"
    assert settings.history_db_path == (tmp_path / "history.db").resolve()
    assert settings.dev is True
