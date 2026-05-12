"""Tests for wizard.oauth_step — wraps spotify_core.spotify_client PKCE flow."""
import os
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from rich.console import Console

from spotify_mcp.wizard import oauth_step


@pytest.fixture
def temp_install(tmp_path, monkeypatch):
    monkeypatch.setenv("SPOTIFY_MCP_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("SPOTIFY_MCP_DATA_DIR", str(tmp_path / "data"))
    (tmp_path / "cfg").mkdir()
    (tmp_path / "data").mkdir()
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "fake-client-id")
    monkeypatch.setenv("TOKEN_ENCRYPT_KEY", Fernet.generate_key().decode())
    import importlib

    import spotify_core.paths as p
    importlib.reload(p)
    from spotify_core.db.migrations import init_tokens_db
    init_tokens_db(p.tokens_db())
    return tmp_path


def test_run_oauth_skips_when_tokens_valid_and_not_forced(temp_install, monkeypatch):
    monkeypatch.setattr(
        "spotify_mcp.wizard.state.tokens_valid", lambda: True
    )
    called = {"flag": False}

    def _stub(**kwargs):
        called["flag"] = True
        return {}

    monkeypatch.setattr("spotify_core.spotify_client.auth.run_pkce_flow", _stub)
    oauth_step.run_oauth(console=Console(), force=False)
    assert called["flag"] is False
