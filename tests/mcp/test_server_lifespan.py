"""Tests for the MCP server lifespan — fail-fast on missing config."""
import asyncio
import importlib
import site
import sys
from pathlib import Path

import pytest


def test_lifespan_writes_actionable_stderr_when_dbs_missing(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("SPOTIFY_CONFIG", str(tmp_path / "cfg" / "config.json"))
    monkeypatch.setenv("SPOTIFY_DATA_DIR", str(tmp_path / "data"))

    apps_mcp = Path(__file__).resolve().parents[2] / "apps" / "mcp"
    monkeypatch.syspath_prepend(str(apps_mcp))
    for site_dir in reversed(site.getsitepackages()):
        monkeypatch.syspath_prepend(site_dir)

    import spotify_core.paths as p

    importlib.reload(p)
    for mod in list(sys.modules):
        if mod.startswith("spotify_mcp"):
            monkeypatch.delitem(sys.modules, mod, raising=False)

    apps_mcp_pkg = apps_mcp / "spotify_mcp"
    assert apps_mcp_pkg.exists()

    import spotify_mcp._mcp as _mcp_mod  # type: ignore

    importlib.reload(_mcp_mod)
    lifespan = _mcp_mod.lifespan
    mcp = _mcp_mod.mcp

    async def _run():
        async with lifespan(mcp):
            pass

    with pytest.raises(SystemExit):
        asyncio.run(_run())

    captured = capsys.readouterr()
    # Claude Desktop shows the server's stderr and nothing else, so this is the
    # only place a user finds out why it refused to start. It has to say what to
    # do, not just that something is wrong.
    assert "not configured" in captured.err
    assert captured.err.count("  - ") >= 1, "no actionable steps listed"
    # ASCII only: Claude Desktop reads this on Windows consoles (cp1252), where
    # an em-dash produces un-decodable bytes.
    assert captured.err.isascii()
