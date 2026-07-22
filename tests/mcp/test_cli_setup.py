"""Tests for the spotify-mcp CLI skeleton (setup/doctor/reauth subcommands)."""
import json

from typer.testing import CliRunner

from spotify_mcp.cli import app

runner = CliRunner()


def test_help_lists_subcommands():
    """--help output must mention setup, doctor, and reauth."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0, result.output
    assert "setup" in result.output
    assert "doctor" in result.output
    assert "reauth" in result.output
    


def test_doctor_runs_without_arguments():
    """doctor command runs without arguments and exits 0 or 1."""
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code in (0, 1), (
        f"Expected exit code 0 or 1, got {result.exit_code}. Output:\n{result.output}"
    )


def test_doctor_outputs_json():
    """`doctor --json` outputs valid JSON to stdout.

    `--json` is the machine contract (the Tauri Setup page reads it); plain
    `doctor` is the human path and prints through rich, which emits ANSI colour
    whenever the terminal supports it -- asserting JSON there passed only as
    long as nothing set FORCE_COLOR.
    """
    result = runner.invoke(app, ["doctor", "--json"])
    # The output should contain parseable JSON
    try:
        data = json.loads(result.output.strip())
    except json.JSONDecodeError as exc:
        raise AssertionError(
            f"doctor output is not valid JSON: {exc}\nOutput:\n{result.output}"
        ) from exc
    assert "ready" in data


def test_setup_resumes_when_already_configured(tmp_path, monkeypatch):
    """If state checks pass, the wizard should not re-run completed steps."""
    monkeypatch.setenv("SPOTIFY_MCP_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("SPOTIFY_MCP_DATA_DIR", str(tmp_path / "data"))

    import spotify_mcp.wizard.state as state

    monkeypatch.setattr(state, "has_client_id", lambda: True)
    monkeypatch.setattr(state, "has_fernet_key", lambda: True)
    monkeypatch.setattr(state, "dbs_initialized", lambda: True)
    monkeypatch.setattr(state, "tokens_valid", lambda: True)
    monkeypatch.setattr(state, "history_has_data", lambda: True)

    import spotify_mcp.wizard.claude_desktop as cdk
    import spotify_mcp.wizard.credentials as cr
    import spotify_mcp.wizard.history_import as hi
    import spotify_mcp.wizard.langfuse_keys as lfk
    import spotify_mcp.wizard.llm_keys as lk
    import spotify_mcp.wizard.oauth_step as os_
    import spotify_mcp.wizard.spotify_app as sa

    called: list[str] = []
    monkeypatch.setattr(sa, "run_step", lambda **k: called.append("spotify_app"))
    monkeypatch.setattr(cr, "prompt_client_id", lambda console: called.append("client_id") or "x")
    monkeypatch.setattr(cr, "ensure_fernet_key", lambda console: called.append("fernet") or "x")
    monkeypatch.setattr(os_, "run_oauth", lambda **k: called.append("oauth"))
    monkeypatch.setattr(hi, "run_step", lambda **k: called.append("history"))
    monkeypatch.setattr(lk, "run_step", lambda **k: called.append("llm_keys"))
    monkeypatch.setattr(lfk, "run_step", lambda **k: called.append("langfuse_keys"))
    monkeypatch.setattr(cdk, "run_step", lambda **k: called.append("claude_desktop"))

    import spotify_mcp.wizard as wiz
    monkeypatch.setattr(wiz, "_dashboard_installed", lambda: True)

    result = runner.invoke(app, ["setup"])

    assert result.exit_code == 0
    assert called == ["llm_keys", "langfuse_keys", "claude_desktop"]


def _table_exists(db_path, table: str) -> bool:
    import sqlite3
    from contextlib import closing
    from pathlib import Path

    db_path = Path(db_path)
    if not db_path.exists():
        return False
    with closing(sqlite3.connect(db_path)) as conn:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
    return row is not None


def test_import_from_path_initializes_history_db(tmp_path, monkeypatch):
    """The promptless `--from` entry skips the wizard's init step, so it must
    create the schema itself — otherwise the Tauri Setup page's import button
    hits `no such table: listening_history` on a fresh install."""
    monkeypatch.setenv("SPOTIFY_MCP_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("SPOTIFY_MCP_DATA_DIR", str(tmp_path / "data"))

    from rich.console import Console
    from spotify_core import paths
    from spotify_mcp.wizard.history_import import import_history

    export_dir = tmp_path / "export"
    export_dir.mkdir()

    # An empty folder is enough: import_json_to_db returns early when it finds no
    # Streaming*.json, so this exercises the init call and nothing else.
    import_history(Console(), import_path=export_dir)

    assert _table_exists(paths.history_db(), "listening_history")


def test_reauth_initializes_tokens_db_before_browser(tmp_path, monkeypatch):
    """Same gap on the OAuth entry, and worse there: a missing table would
    otherwise surface only after the user had already authorized."""
    monkeypatch.setenv("SPOTIFY_MCP_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("SPOTIFY_MCP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("TOKEN_ENCRYPT_KEY", "x" * 44)

    from rich.console import Console
    from spotify_core import paths
    import spotify_mcp.wizard.oauth_step as os_

    seen: dict = {}

    def _fake_flow(**kwargs):
        seen["ready"] = _table_exists(paths.tokens_db(), "spotify_tokens")
        raise RuntimeError("stop before the real token exchange")

    monkeypatch.setattr(os_._auth, "run_pkce_flow", _fake_flow)

    try:
        os_.run_oauth(console=Console(), force=True)
    except RuntimeError:
        pass

    assert seen.get("ready") is True, "tokens.db must be initialized before the browser round-trip"
