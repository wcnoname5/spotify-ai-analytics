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

console = Console()


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
def doctor(
    json_out: Annotated[
        bool, typer.Option("--json", help="Print bare JSON (no colour) for machine callers.")
    ] = False,
) -> None:
    """Check environment readiness and print a JSON report.

    Exits 1 when not ready. During setup that is the *normal* state, so machine
    callers (the Tauri Setup page) must read stdout and ignore the exit code.
    """
    report = _state.collect_report()
    if json_out:
        print(json.dumps(report))
    else:
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
    from spotify_core.db.migrations import init_history_db
    from spotify_core.logging import setup_logging
    # spotify_mcp.config imports spotify_core.config.settings, which reads the
    # platform .env via pydantic-settings; get_client_id/get_fernet_key delegate to it.
    from spotify_mcp.config import DB_PATH, TOKENS_DB, get_client_id, get_fernet_key

    paths.ensure_dirs()
    # Promptless entry (the Tauri Setup page) never runs the wizard's init step,
    # so this path must create the schema itself. Idempotent.
    init_history_db(paths.history_db())

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
def path(
    json_out: Annotated[
        bool, typer.Option("--json", help="Print bare JSON only, omitting the warning lines.")
    ] = False,
) -> None:
    """Show the resolved config/data locations, how each was chosen, and any conflicts."""
    from spotify_core import paths

    from spotify_mcp.wizard import state as _st

    if json_out:
        # Warnings are rich-markup and would corrupt the JSON for machine callers.
        print(json.dumps(paths.describe()))
        return
    console.print_json(json.dumps(paths.describe()))
    for w in _st.path_warnings():
        console.print(f"[yellow]warning: {w}[/yellow]")


cloud_app = typer.Typer(help="Deploy and seed the Cloudflare Worker + D1 backend.")
app.add_typer(cloud_app, name="cloud")


@cloud_app.command("deploy")
def cloud_deploy(
    name: Annotated[
        str, typer.Option("--name", help="D1 database / Worker name. Use a different one for a test stack.")
    ] = "spotify-analytics",
    api_token: Annotated[
        str, typer.Option("--api-token", help="Cloudflare API token. Without it wrangler tries an interactive login.")
    ] = "",
    rotate: Annotated[
        bool, typer.Option("--rotate", help="Mint a new Worker auth token (invalidates every other machine's).")
    ] = False,
) -> None:
    """Create D1, apply migrations, deploy the Worker (cron goes live), set secrets, seed.

    Promptless by design: this is what the Setup page's Deploy button spawns, and
    a `read` here would hang a non-tty child forever.
    """
    import sys

    from spotify_mcp import cloud

    # The GUI streams this into a log pane, where a Python traceback is noise
    # the user cannot act on. Print the message, keep the exit code.
    try:
        code = cloud.deploy(name=name, api_token=api_token, rotate=rotate)
    except RuntimeError as exc:
        # Ours, and already phrased for a human — the class name adds nothing.
        print(str(exc), file=sys.stderr)
        code = 1
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        code = 1
    raise typer.Exit(code=code)


@cloud_app.command("seed")
def cloud_seed(
    force: Annotated[bool, typer.Option("--force", help="Overwrite the token row already in D1.")] = False,
    tokens_only: Annotated[bool, typer.Option("--tokens-only", help="Skip the history push.")] = False,
) -> None:
    """Push local tokens + listening history to D1. Rerun-safe; reads WORKER_* from .env."""
    from spotify_mcp import cloud

    # cloud.seed already turns Worker/HTTP failures into a return code.
    raise typer.Exit(code=cloud.seed(force=force, tokens_only=tokens_only))


config_app = typer.Typer(help="Read and write settings in the resolved .env file.")
app.add_typer(config_app, name="config")


@config_app.command("get")
def config_get() -> None:
    """Print the effective runtime config the desktop app needs, as JSON.

    The app used to get these as build-time Vite `define` constants. They are
    resolved here rather than parsed from .env by the caller because the
    effective value is not a plain file read: HISTORY_DB_PATH falls back to
    paths.history_db() and resolves relative values against the data dir
    (see config.Settings). Keeping that precedence in one place is the point.
    """
    import os

    from spotify_core import env_file, paths
    from spotify_core.config import Settings

    # Fresh instance, not the module singleton: a `config set` earlier in this
    # session must be reflected without the caller restarting the CLI.
    settings = Settings()
    target = paths.env_file()

    def _raw(key: str) -> str:
        return (os.environ.get(key) or env_file.read_key(target, key) or "").strip()

    print(
        json.dumps(
            {
                "env_file": str(target),
                "dev": settings.dev,
                "history_db_path": str(settings.history_db_path),
                "worker_url": _raw("WORKER_URL"),
                "worker_auth_token": _raw("WORKER_AUTH_TOKEN"),
                # Which optional settings already have a value, so the Setup page
                # can show only what is missing. Booleans, never the secrets.
                "configured": {
                    # client_id is the app's "is setup done at all" signal, so it
                    # rides along here rather than costing a second `doctor` spawn.
                    "client_id": bool(_raw("SPOTIFY_CLIENT_ID")),
                    "gemini": bool(settings.gemini_api_key),
                    "openai": bool(settings.openai_api_key),
                    "langfuse": settings.langfuse_configured,
                    "langsmith": bool(settings.langsmith_api_key),
                    "worker": bool(_raw("WORKER_URL") and _raw("WORKER_AUTH_TOKEN")),
                },
            }
        )
    )


@config_app.command("keygen")
def config_keygen() -> None:
    """Ensure a Fernet TOKEN_ENCRYPT_KEY exists, generating one if absent.

    Never overwrites an existing key — regenerating orphans every stored token.
    Reports whether a key was created so the GUI can say so; the key itself is
    not printed, since it would land in the caller's captured stdout.
    """
    from spotify_core import env_file, paths
    from spotify_mcp.wizard import credentials as _credentials

    existed = bool(env_file.read_key(paths.env_file(), "TOKEN_ENCRYPT_KEY"))
    _credentials.ensure_fernet_key(console)
    print(json.dumps({"created": not existed}))


@config_app.command("set")
def config_set(
    pairs: Annotated[list[str], typer.Argument(help="One or more KEY=VALUE pairs.")],
) -> None:
    """Upsert KEY=VALUE pairs into the resolved .env, leaving sibling keys untouched."""
    from spotify_core import env_file, paths

    target = paths.env_file()
    for pair in pairs:
        key, sep, value = pair.partition("=")
        key = key.strip()
        if not sep or not key:
            raise typer.BadParameter(f"expected KEY=VALUE, got {pair!r}")
        env_file.upsert(target, key, value)
    print(json.dumps({"env_file": str(target), "written": len(pairs)}))

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
