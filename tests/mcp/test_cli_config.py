"""Tests for the machine-facing CLI surface used by the Tauri Setup page.

`config set` is the write half of the GUI's runtime config (reads are parsed in
Rust; writes go through env_file.upsert so the merge logic lives in one place).
The `--json` flags exist so the Rust side can parse stdout without rich markup.
"""
import json

from typer.testing import CliRunner

from spotify_core import env_file
from spotify_mcp.cli import app

runner = CliRunner()


def _env_at(tmp_path, monkeypatch):
    """Point path resolution at a throwaway config dir and return its .env."""
    monkeypatch.setenv("SPOTIFY_MCP_CONFIG_DIR", str(tmp_path))
    return tmp_path / ".env"


def test_config_set_upserts_without_disturbing_siblings(tmp_path, monkeypatch):
    """Existing keys are replaced, new keys appended, unrelated keys untouched."""
    env = _env_at(tmp_path, monkeypatch)
    env.write_text("KEEP_ME=untouched\nSPOTIFY_CLIENT_ID=old\n")

    result = runner.invoke(
        app, ["config", "set", "SPOTIFY_CLIENT_ID=new", "LANGSMITH_API_KEY=ls_abc"]
    )

    assert result.exit_code == 0, result.output
    assert env_file.read_key(env, "KEEP_ME") == "untouched"
    assert env_file.read_key(env, "SPOTIFY_CLIENT_ID") == "new"
    assert env_file.read_key(env, "LANGSMITH_API_KEY") == "ls_abc"


def test_config_set_creates_env_when_absent(tmp_path, monkeypatch):
    """First-run: no .env yet, so `config set` must create it."""
    env = _env_at(tmp_path, monkeypatch)
    assert not env.exists()

    result = runner.invoke(app, ["config", "set", "SPOTIFY_CLIENT_ID=abc"])

    assert result.exit_code == 0, result.output
    assert env_file.read_key(env, "SPOTIFY_CLIENT_ID") == "abc"


def test_config_set_rejects_malformed_pair(tmp_path, monkeypatch):
    """A bare token with no '=' is a usage error, not a silently ignored no-op."""
    _env_at(tmp_path, monkeypatch)
    result = runner.invoke(app, ["config", "set", "NOT_A_PAIR"])
    assert result.exit_code != 0


def test_config_set_keeps_values_containing_equals(tmp_path, monkeypatch):
    """Only the first '=' separates key from value — base64 keys end in '='."""
    env = _env_at(tmp_path, monkeypatch)
    result = runner.invoke(app, ["config", "set", "TOKEN_ENCRYPT_KEY=YWJj=="])
    assert result.exit_code == 0, result.output
    assert env_file.read_key(env, "TOKEN_ENCRYPT_KEY") == "YWJj=="


def test_path_json_is_parseable(tmp_path, monkeypatch):
    """--json must emit bare JSON: no rich colour codes, no trailing warnings."""
    _env_at(tmp_path, monkeypatch)
    result = runner.invoke(app, ["path", "--json"])
    assert result.exit_code == 0, result.output
    assert "env_file" in json.loads(result.stdout)


def test_doctor_json_is_parseable_even_when_not_ready(tmp_path, monkeypatch):
    """doctor exits 1 when unconfigured — stdout must still be valid JSON.

    This is the normal state mid-setup, which is why the GUI reads stdout and
    ignores the exit code.
    """
    _env_at(tmp_path, monkeypatch)
    monkeypatch.setenv("SPOTIFY_MCP_DATA_DIR", str(tmp_path / "data"))
    result = runner.invoke(app, ["doctor", "--json"])
    assert result.exit_code in (0, 1)
    assert "ready" in json.loads(result.stdout)
