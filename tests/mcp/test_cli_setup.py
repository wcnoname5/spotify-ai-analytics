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
    """doctor command outputs valid JSON to stdout."""
    result = runner.invoke(app, ["doctor"])
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
    import spotify_mcp.wizard.oauth_step as os_
    import spotify_mcp.wizard.spotify_app as sa

    called: list[str] = []
    monkeypatch.setattr(sa, "run_step", lambda **k: called.append("spotify_app"))
    monkeypatch.setattr(cr, "prompt_client_id", lambda console: called.append("client_id") or "x")
    monkeypatch.setattr(cr, "ensure_fernet_key", lambda console: called.append("fernet") or "x")
    monkeypatch.setattr(os_, "run_oauth", lambda **k: called.append("oauth"))
    monkeypatch.setattr(hi, "run_step", lambda **k: called.append("history"))
    monkeypatch.setattr(cdk, "run_step", lambda **k: called.append("claude_desktop"))

    result = runner.invoke(app, ["setup"])

    assert result.exit_code == 0
    assert called == ["claude_desktop"]
