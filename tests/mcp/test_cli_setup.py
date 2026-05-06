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
