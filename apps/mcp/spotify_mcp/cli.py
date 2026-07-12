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
from importlib.metadata import PackageNotFoundError, version as _pkg_version
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console

from spotify_mcp.wizard import run_wizard
from spotify_mcp.wizard import history_import as _history_import
from spotify_mcp.wizard import oauth_step as _oauth_step
from spotify_mcp.wizard import state as _state

from loguru import logger

from spotify_mcp.dashboard.dependencies import dashboard_available

console = Console()


def _dashboard_available() -> bool:
    """True when the [dashboard] extra's startup dependencies are importable."""
    return dashboard_available()


app = typer.Typer(
    name="spotify-mcp",
    no_args_is_help=False,
    add_completion=False,
    help="Spotify MCP setup and management CLI.",
)


def _version_callback(value: bool) -> None:
    if not value:
        return
    try:
        v = _pkg_version("spotify-analytics-mcp")
    except PackageNotFoundError:
        v = "unknown (running from source?)"
    console.print(f"spotify-analytics-mcp {v}")
    raise typer.Exit()


@app.callback(invoke_without_command=True)
def _default(
    ctx: typer.Context,
    _version: Annotated[
        bool,
        typer.Option(
            "--version",
            help="Show the installed version and exit.",
            callback=_version_callback,
            is_eager=True,
        ),
    ] = False,
) -> None:
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

    from spotify_core import env_file as _env_file
    from spotify_core import paths
    from spotify_core.logging import setup_logging
    # spotify_mcp.config imports spotify_core.config.settings, which reads the
    # platform .env via pydantic-settings; get_client_id/get_fernet_key delegate to it.
    from spotify_mcp.config import DB_PATH, TOKENS_DB, get_client_id, get_fernet_key

    paths.ensure_dirs()

    # Setup logging
    level = "DEBUG" if verbose else os.getenv("LOG_LEVEL", "INFO").upper()
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

        logger.info("Syncing recent plays for user '{}'", final_user_id)
        result = sync_api_to_db(
            db_path=DB_PATH,
            tokens_db_path=TOKENS_DB,
            user_id=final_user_id,
            client_id=client_id,
            fernet_key=fernet_key,
        )
        logger.info(
            "Inserted {} rows, cursor updated to {} ms",
            result["inserted"], result["cursor_ms"]
        )
        console.print(f"[green]✓ Synced {result['inserted']} new plays (cursor: {result['cursor_ms']} ms)[/green]")
    except Exception as exc:
        logger.error("Sync failed: {}", exc)
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(code=1)


@app.command()
def path() -> None:
    """Show the resolved config/data locations, how each was chosen, and any conflicts."""
    from spotify_core import paths

    from spotify_mcp.wizard import state as _st

    console.print_json(json.dumps(paths.describe()))
    for w in _st.path_warnings():
        console.print(f"[yellow]warning: {w}[/yellow]")

@app.command()
def dashboard(
    port: Annotated[int, typer.Option("--port", help="Port for the Streamlit server.")] = 8501,
) -> None:
    """Launch the Streamlit dashboard (requires the dashboard extra)."""
    import subprocess
    import sys
    from importlib.resources import as_file, files

    if not _dashboard_available():
        # NB: escape the literal brackets so Rich does not treat [dashboard] as markup.
        console.print(
            "[red]Dashboard dependencies are not installed.[/red]\n"
            'Install with:  uvx --from "spotify-analytics-mcp\\[dashboard]" spotify-mcp dashboard'
        )
        raise typer.Exit(code=1)

    with as_file(files("spotify_mcp.dashboard") / "main_page.py") as page:
        result = subprocess.run(
            [sys.executable, "-m", "streamlit", "run", str(page), "--server.port", str(port)]
        )
    if result.returncode:
        raise typer.Exit(code=result.returncode)


@app.command()
def serve() -> None:
    """Start the MCP server over stdio (invoked by Claude Desktop)."""
    import os

    from dotenv import load_dotenv

    from spotify_core import paths
    from spotify_core.logging import setup_mcp_logging

    paths.ensure_dirs()
    # Load the platform .env into os.environ so env-based SDKs (e.g. Langfuse) see
    # their credentials. The cwd .env is a dev-checkout fallback (no override).
    load_dotenv(paths.env_file())
    load_dotenv(override=False)

    setup_mcp_logging(level=os.getenv("LOG_LEVEL", "DEBUG").upper())

    from spotify_mcp._mcp import main
    main()
