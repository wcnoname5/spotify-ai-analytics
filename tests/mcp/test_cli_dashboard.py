"""Tests for the `spotify-mcp dashboard` command."""
import subprocess

from typer.testing import CliRunner

import spotify_mcp.cli as cli
from spotify_mcp.cli import app

runner = CliRunner()


def test_dashboard_exits_when_dashboard_dependencies_missing(monkeypatch):
    monkeypatch.setattr(cli, "_dashboard_available", lambda: False)
    result = runner.invoke(app, ["dashboard"])
    assert result.exit_code == 1, result.output
    assert "dashboard" in result.output.lower()
    # The install hint must show the literal extra name, not have it stripped as Rich markup.
    assert "[dashboard]" in result.output


def test_dashboard_launches_streamlit(monkeypatch):
    monkeypatch.setattr(cli, "_dashboard_available", lambda: True)
    captured = {}

    def fake_run(cmd, *args, **kwargs):
        captured["cmd"] = cmd

        class _Result:
            returncode = 0

        return _Result()

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = runner.invoke(app, ["dashboard", "--port", "8600"])
    assert result.exit_code == 0, result.output

    cmd = captured["cmd"]
    assert "-m" in cmd and "streamlit" in cmd and "run" in cmd
    assert cmd[-2:] == ["--server.port", "8600"]
    assert any("main_page.py" in str(part) for part in cmd)


def test_dashboard_exits_with_streamlit_return_code(monkeypatch):
    monkeypatch.setattr(cli, "_dashboard_available", lambda: True)

    def fake_run(cmd, *args, **kwargs):
        class _Result:
            returncode = 7

        return _Result()

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = runner.invoke(app, ["dashboard"])

    assert result.exit_code == 7, result.output
