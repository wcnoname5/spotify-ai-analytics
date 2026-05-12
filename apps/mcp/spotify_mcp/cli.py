"""CLI entry point for spotify-mcp.

Usage:
    spotify-mcp              # defaults to 'setup'
    spotify-mcp setup        # interactive setup wizard
    spotify-mcp import-history [--from <path>]
    spotify-mcp doctor       # check environment readiness
    spotify-mcp reauth       # re-run OAuth flow
    spotify-mcp sync         # sync recent plays from Spotify API
    spotify-mcp serve        # start the MCP server (used by Claude Desktop)
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console

from spotify_mcp.wizard import run_wizard
from spotify_mcp.wizard import history_import as _history_import
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
        ctx.invoke(setup)


@app.command()
def setup(
    setup_claude_desktop: Annotated[
        bool,
        typer.Option("--setup-claude-desktop", help="Register the MCP server with Claude Desktop."),
    ] = False,
) -> None:
    """Run the interactive setup wizard."""
    _setup(setup_claude_desktop=setup_claude_desktop)


def _setup(setup_claude_desktop: bool) -> None:
    """Internal helper shared by the default callback and the setup subcommand."""
    try:
        run_wizard(setup_claude_desktop=setup_claude_desktop)
    except NotImplementedError:
        console.print("[yellow]Setup wizard is not yet implemented.[/yellow]")


@app.command("import-history")
def import_history(
    from_path: Annotated[
        Optional[Path],
        typer.Option("--from", help="Path to a Spotify history export file or folder to import."),
    ] = None,
) -> None:
    """Import Spotify listening history from a JSON export file or folder."""
    _history_import.import_history(console=console, import_path=from_path)


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


@app.command()
def sync(
    user_id: Annotated[
        Optional[str],
        typer.Option("--user-id", help="Spotify user ID (defaults to SPOTIFY_USER_ID from .env)"),
    ] = None,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Enable verbose logging"),
    ] = False,
) -> None:
    """Fetch recent plays from Spotify API and upsert into local database.

    This syncs the most recent ~50 plays. Run this periodically to keep
    your local history up to date.
    """
    import os

    from dotenv import load_dotenv

    from spotify_core import env_file as _env_file
    from spotify_core import paths
    from spotify_core.logging import setup_logging
    from spotify_mcp.config import DB_PATH, TOKENS_DB, get_client_id, get_fernet_key

    paths.ensure_dirs()
    if paths.env_file().exists():
        load_dotenv(paths.env_file())

    # Setup logging
    level = logging.DEBUG if verbose else logging.getLevelNamesMapping().get(
        os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO
    )
    setup_logging(log_name="sync", level=level)

    # Determine user ID: CLI flag > wizard config > "default" (matches OAuth default)
    final_user_id = (
        user_id
        or _env_file.read_key(paths.env_file(), "SPOTIFY_USER_ID")
        or "default"
    )

    # Check required credentials
    try:
        client_id = get_client_id()
        fernet_key = get_fernet_key()
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(code=1)

    # Run sync
    try:
        from spotify_core.db.pipeline import sync_api_to_db

        logger.info("Syncing recent plays for user '%s'", final_user_id)
        result = sync_api_to_db(
            db_path=DB_PATH,
            tokens_db_path=TOKENS_DB,
            user_id=final_user_id,
            client_id=client_id,
            fernet_key=fernet_key,
        )
        logger.info(
            "Inserted %d rows, cursor updated to %d ms",
            result["inserted"], result["cursor_ms"]
        )
        console.print(f"[green]✓ Synced {result['inserted']} new plays (cursor: {result['cursor_ms']} ms)[/green]")
    except Exception as exc:
        logger.error("Sync failed: %s", exc)
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(code=1)


@app.command()
def path() -> None:
    """Print the default path to save the local SQLite database and Configuration files"""
    from dotenv import load_dotenv

    from spotify_core import paths

    if paths.env_file().exists():
        load_dotenv(paths.env_file())
    config_dir = paths.config_dir()
    data_dir = paths.data_dir()
    console.print(f"[yellow]Config directory: {config_dir}; Data directory: {data_dir}[/yellow]")

@app.command()
def serve() -> None:
    """Start the MCP server over stdio (invoked by Claude Desktop)."""
    import logging
    import os

    from dotenv import load_dotenv

    from spotify_core import paths
    from spotify_core.logging import setup_mcp_logging

    paths.ensure_dirs()
    if paths.env_file().exists():
        load_dotenv(paths.env_file())
    load_dotenv(override=False)

    _raw_level = os.getenv("LOG_LEVEL", "DEBUG").upper()
    setup_mcp_logging(level=logging.getLevelNamesMapping().get(_raw_level, logging.DEBUG))

    from spotify_mcp._mcp import main
    main()
