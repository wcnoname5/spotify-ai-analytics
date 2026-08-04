"""Tests for wizard.state — resumability checks."""
import os
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from spotify_mcp.wizard import state as st


@pytest.fixture
def temp_install(tmp_path, monkeypatch):
    cfg = tmp_path / "cfg"
    data = tmp_path / "data"
    cfg.mkdir()
    data.mkdir()
    monkeypatch.setenv("SPOTIFY_CONFIG", str(cfg / "config.json"))
    monkeypatch.setenv("SPOTIFY_DATA_DIR", str(data))
    # Force a clean import so paths re-resolve
    import importlib

    import spotify_core.paths as p
    importlib.reload(p)
    return cfg, data


def test_no_client_id_when_env_missing(temp_install, monkeypatch):
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    cfg, _ = temp_install
    assert st.has_client_id() is False


def test_has_client_id_reads_from_env_file(temp_install):
    cfg, _ = temp_install
    (cfg / ".env").write_text("SPOTIFY_CLIENT_ID=abc123\n")
    assert st.has_client_id() is True


def test_has_fernet_key_reads_from_env_file(temp_install):
    cfg, _ = temp_install
    (cfg / ".env").write_text(f"TOKEN_ENCRYPT_KEY={Fernet.generate_key().decode()}\n")
    assert st.has_fernet_key() is True


def test_dbs_initialized_false_when_missing(temp_install):
    assert st.dbs_initialized() is False


def test_dbs_initialized_true_after_init(temp_install):
    from spotify_core.db.migrations import init_history_db, init_tokens_db
    from spotify_core import paths

    init_history_db(paths.history_db())
    init_tokens_db(paths.tokens_db())
    assert st.dbs_initialized() is True


def test_tokens_valid_false_when_no_row(temp_install):
    from spotify_core.db.migrations import init_tokens_db
    from spotify_core import paths

    init_tokens_db(paths.tokens_db())
    assert st.tokens_valid() is False


def test_collect_report_lists_all_checks(temp_install):
    report = st.collect_report()
    assert set(report["checks"].keys()) >= {
        "client_id", "fernet_key", "dbs_initialized", "tokens_valid"
    }
    assert isinstance(report["actions_needed"], list)
    assert isinstance(report["ready"], bool)
    assert "message" in report
