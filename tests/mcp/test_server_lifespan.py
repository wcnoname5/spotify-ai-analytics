"""Tests for the MCP server lifespan — fail-fast on missing config."""
import asyncio
import importlib
import site
import sys
from pathlib import Path

import pytest


def test_lifespan_writes_actionable_stderr_when_dbs_missing(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("SPOTIFY_MCP_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("SPOTIFY_MCP_DATA_DIR", str(tmp_path / "data"))

    apps_mcp = Path(__file__).resolve().parents[2] / "apps" / "mcp"
    monkeypatch.syspath_prepend(str(apps_mcp))
    for site_dir in reversed(site.getsitepackages()):
        monkeypatch.syspath_prepend(site_dir)

    import spotify_core.paths as p

    importlib.reload(p)
    sys.modules.pop("server", None)
    sys.modules.pop("mcp", None)
    from server import lifespan, mcp  # type: ignore

    async def _run():
        async with lifespan(mcp):
            pass

    with pytest.raises(SystemExit):
        asyncio.run(_run())

    captured = capsys.readouterr()
    assert "spotify-mcp setup" in captured.err
