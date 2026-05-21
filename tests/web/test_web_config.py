"""Tests for spotify_web.config sync-credential resolution."""
from spotify_web import config as web_config


def test_get_client_id_reads_env(monkeypatch):
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "cid-123")
    assert web_config.get_client_id() == "cid-123"


def test_get_client_id_missing(monkeypatch):
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    assert web_config.get_client_id() == ""


def test_get_fernet_key_reads_env(monkeypatch):
    monkeypatch.setenv("TOKEN_ENCRYPT_KEY", "k-abc")
    assert web_config.get_fernet_key() == b"k-abc"


def test_get_fernet_key_missing(monkeypatch):
    monkeypatch.delenv("TOKEN_ENCRYPT_KEY", raising=False)
    assert web_config.get_fernet_key() == b""


def test_get_sync_args_shape(monkeypatch):
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "cid")
    monkeypatch.setenv("TOKEN_ENCRYPT_KEY", "key")
    args = web_config.get_sync_args()
    assert set(args) == {
        "db_path", "tokens_db_path", "user_id", "client_id", "fernet_key",
    }
    assert args["client_id"] == "cid"
    assert args["fernet_key"] == b"key"
    assert isinstance(args["db_path"], str)
    assert isinstance(args["tokens_db_path"], str)
