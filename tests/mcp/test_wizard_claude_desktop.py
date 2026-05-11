"""Tests for wizard.claude_desktop — locate, diff, and merge the config."""
import json
from pathlib import Path

import pytest
from rich.console import Console

from spotify_mcp.wizard import claude_desktop as cd


def test_build_entry_uses_resolved_path():
    entry = cd.build_entry(script_path="/home/u/.local/bin/spotify-mcp")
    assert entry["command"] == "/home/u/.local/bin/spotify-mcp"
    assert entry["args"] == ["serve"]


def test_compute_merge_into_empty(tmp_path):
    cfg = tmp_path / "claude_desktop_config.json"
    merged = cd.compute_merged(cfg, entry={"command": "X", "args": []})
    assert merged == {"mcpServers": {"spotify-mcp": {"command": "X", "args": []}}}


def test_compute_merge_preserves_other_keys(tmp_path):
    cfg = tmp_path / "claude_desktop_config.json"
    cfg.write_text(json.dumps({
        "mcpServers": {"other": {"command": "Y", "args": []}},
        "theme": "dark",
    }))
    merged = cd.compute_merged(cfg, entry={"command": "X", "args": []})
    assert merged["mcpServers"]["other"] == {"command": "Y", "args": []}
    assert merged["mcpServers"]["spotify-mcp"] == {"command": "X", "args": []}
    assert merged["theme"] == "dark"


def test_write_with_backup_creates_timestamped_backup(tmp_path):
    cfg = tmp_path / "claude_desktop_config.json"
    cfg.write_text(json.dumps({"existing": True}))
    cd.write_with_backup(cfg, {"merged": True})
    assert cfg.read_text() == json.dumps({"merged": True}, indent=2)
    # exactly one backup file
    backups = list(tmp_path.glob("claude_desktop_config.json.bak.*"))
    assert len(backups) == 1
    assert json.loads(backups[0].read_text()) == {"existing": True}


def test_diff_text_shows_added_entry(tmp_path):
    cfg = tmp_path / "claude_desktop_config.json"
    diff = cd.diff_text(cfg, {"mcpServers": {"spotify-mcp": {"command": "X", "args": []}}})
    assert "spotify-mcp" in diff
    assert "+" in diff  # diff markers
