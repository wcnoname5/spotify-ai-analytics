"""Wizard step: locate Claude Desktop config, show a diff, merge with backup."""
import difflib
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional  # noqa: F401 — kept for write_with_backup return type

from rich.console import Console
from rich.syntax import Syntax


def default_config_path() -> Path:
    """Per-OS path Claude Desktop reads its MCP config from."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    if sys.platform == "win32":
        appdata = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return appdata / "Claude" / "claude_desktop_config.json"
    # Linux + others
    return Path.home() / ".config" / "Claude" / "claude_desktop_config.json"


def build_entry() -> dict:
    """Build the MCP server entry using uvx so Claude Desktop users get automatic updates."""
    return {
        "command": "uvx",
        "args": ["--from", "spotify-analytics-mcp", "spotify-mcp", "serve"],
    }


def compute_merged(config_path: Path, entry: dict) -> dict:
    """Return the merged config dict (does not write)."""
    if config_path.exists():
        try:
            current = json.loads(config_path.read_text())
        except json.JSONDecodeError:
            current = {}
    else:
        current = {}

    servers = current.get("mcpServers", {})
    servers["spotify-mcp"] = entry
    current["mcpServers"] = servers
    return current


def diff_text(config_path: Path, merged: dict) -> str:
    """Unified diff between current file and proposed merged content."""
    before = config_path.read_text() if config_path.exists() else ""
    after = json.dumps(merged, indent=2)
    return "\n".join(
        difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile=str(config_path),
            tofile=str(config_path) + " (proposed)",
            lineterm="",
        )
    )


def write_with_backup(config_path: Path, merged: dict) -> Optional[Path]:
    """Write merged content; back up any existing file. Returns backup path or None."""
    config_path.parent.mkdir(parents=True, exist_ok=True)
    backup: Optional[Path] = None
    if config_path.exists():
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = config_path.with_name(f"{config_path.name}.bak.{ts}")
        shutil.copy2(config_path, backup)
    config_path.write_text(json.dumps(merged, indent=2))
    return backup


def run_step(console: Console, install: bool) -> None:
    """The full Claude Desktop config step.

    With install=False, prints the snippet for manual copy. With install=True,
    locates the config, shows a diff, asks for confirmation, then writes with backup.
    """
    entry = build_entry()
    snippet = json.dumps({"mcpServers": {"spotify-mcp": entry}}, indent=2)

    cfg_path = default_config_path()
    if not cfg_path.exists():
        location_msg = (
            f"[yellow]Claude Desktop config not found at {cfg_path}.\n"
            "Open Claude Desktop → Help → Troubleshooting → Enable Developer Mode, then re-run.\n"
            "If the file still doesn't appear, open it via "
            "Developer Mode → Open App Config File... and paste the snippet below manually:[/yellow]\n"
        )
    else:
        location_msg = f"\nConfig location: {default_config_path()}"

    if not install or not cfg_path.exists():
        console.print("\n[bold]Add this to your Claude Desktop config:[/bold]\n")
        console.print(location_msg)
        console.print(Syntax(snippet, "json", theme="ansi_dark"))
        return

    # If we found the config file, show a diff and ask before writing.
    merged = compute_merged(cfg_path, entry)
    console.print("\n[bold]Proposed change to Claude Desktop config:[/bold]")
    console.print(diff_text(cfg_path, merged) or "(no diff — entry already present)")
    confirm = console.input("\nApply this change? [y/N] ").strip().lower()
    if confirm != "y":
        console.print("Skipped. The snippet above is yours to paste manually.")
        return

    backup = write_with_backup(cfg_path, merged)
    console.print(f"[green]Updated {cfg_path}.[/green]")
    if backup:
        console.print(f"Backup: {backup}")
