"""Tests for wizard.credentials — client_id and Fernet key persistence."""
import os
from pathlib import Path

import pytest
from rich.console import Console

from spotify_mcp.wizard import credentials


@pytest.fixture
def temp_cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("SPOTIFY_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.setenv("SPOTIFY_DATA_DIR", str(tmp_path / "data"))
    import importlib

    import spotify_core.paths as p
    importlib.reload(p)
    return tmp_path


def test_persist_client_id_writes_env(temp_cfg):
    credentials.persist_client_id("abc123def456")
    env = (temp_cfg / ".env").read_text()
    assert "SPOTIFY_CLIENT_ID=abc123def456" in env


def test_persist_client_id_strips_whitespace(temp_cfg):
    credentials.persist_client_id("  abc123  ")
    env = (temp_cfg / ".env").read_text()
    assert "SPOTIFY_CLIENT_ID=abc123" in env


def test_persist_client_id_rejects_empty(temp_cfg):
    with pytest.raises(ValueError):
        credentials.persist_client_id("")


def test_ensure_fernet_key_creates_when_missing(temp_cfg):
    console = Console(record=True)
    key = credentials.ensure_fernet_key(console=console)
    from cryptography.fernet import Fernet
    Fernet(key.encode())  # must round-trip as a valid key


def test_ensure_fernet_key_skips_when_present(temp_cfg):
    from cryptography.fernet import Fernet
    existing = Fernet.generate_key().decode()
    (temp_cfg / ".env").write_text(f"TOKEN_ENCRYPT_KEY={existing}\n")
    console = Console(record=True)
    key = credentials.ensure_fernet_key(console=console)
    assert key == existing
