"""CLI entry point for spotify-mcp.

Usage:
    spotify-mcp              # defaults to 'setup'
    spotify-mcp setup        # interactive setup wizard
    spotify-mcp doctor       # check environment readiness
    spotify-mcp reauth       # re-run OAuth flow
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console

from spotify_mcp.wizard import run_wizard
from spotify_mcp.wizard import oauth_step as _oauth_step
from spotify_mcp.wizard import state as _state

logger = logging.getLogger(__name__)

console = Console()

app = typer.Typer(
    name="spotify-mcp",
    no_args_is_help=False,
    add_completion=False,
    help="Spotify MCP setup and management CLI.",
)


@app.callback(invoke_without_command=True)
def _default(ctx: typer.Context) -> None:
    """Default action when no subcommand is given: run setup."""
    if ctx.invoked_subcommand is None:
        _setup(setup_claude_desktop=False, import_path=None)


@app.command()
def setup(
    setup_claude_desktop: Annotated[
        bool,
        typer.Option("--setup-claude-desktop", help="Register the MCP server with Claude Desktop."),
    ] = False,
    import_path: Annotated[
        Optional[Path],
        typer.Option("--import", help="Path to a Spotify history export to import."),
    ] = None,
) -> None:
    """Run the interactive setup wizard."""
    _setup(setup_claude_desktop=setup_claude_desktop, import_path=import_path)


def _setup(setup_claude_desktop: bool, import_path: Optional[Path]) -> None:
    """Internal helper shared by the default callback and the setup subcommand."""
    try:
        run_wizard(setup_claude_desktop=setup_claude_desktop, import_path=import_path)
    except NotImplementedError:
        console.print("[yellow]Setup wizard is not yet implemented.[/yellow]")


@app.command()
def doctor() -> None:
    """Check environment readiness and print a JSON report."""
    report = _state.collect_report()
    console.print_json(json.dumps(report))
    is_ready: bool = bool(report.get("ready", False))
    raise typer.Exit(code=0 if is_ready else 1)


@app.command()
def reauth() -> None:
    """Re-run the Spotify OAuth authorisation flow."""
    try:
        _oauth_step.run_oauth(console=console, force=True)
    except NotImplementedError:
        console.print("[yellow]OAuth step is not yet implemented.[/yellow]")
