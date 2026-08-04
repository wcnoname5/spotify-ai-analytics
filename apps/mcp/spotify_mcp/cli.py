"""CLI entry point for spotify-mcp.

Usage:
    spotify-mcp config       # show resolved paths and which settings are set
    spotify-mcp doctor       # check environment readiness
    spotify-mcp cloud pull   # refresh the local SQLite cache from D1
    spotify-mcp cloud deploy # create/update the Worker + D1 (needs node)
    spotify-mcp mcp-config   # print the Claude Desktop MCP entry
    spotify-mcp serve        # start the MCP server (used by Claude Desktop)

Setup is the desktop app's job now, so `setup`, `reauth`, `import-history` and
`sync` are gone:

- `setup` was an interactive Typer wizard duplicating the app's Setup page.
- `reauth` ran the OAuth flow; the app does it (`apps/tauri/src/lib/oauth.ts`),
  and tokens go straight to D1 rather than to a local tokens.db.
- `import-history` read a data export with Polars and wrote to the *local*
  SQLite, which was backwards — that copy is a disposable mirror of D1.
- `sync` needed the Spotify tokens on this machine. They only exist in D1 now,
  so the Worker is the only thing that can do it: `POST /api/sync`.

What is left is diagnostics, the D1 -> local cache pull that MCP and report
generation read, and the MCP server itself.
"""
from __future__ import annotations

import json
from importlib.metadata import PackageNotFoundError, version as _pkg_version
from typing import Annotated

import typer
from rich.console import Console

console = Console()


app = typer.Typer(
    name="spotify-mcp",
    no_args_is_help=True,
    add_completion=False,
    help="Spotify MCP diagnostics and management CLI. Setup lives in the desktop app.",
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


@app.callback()
def _default(
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
    """Spotify MCP diagnostics and management CLI."""


def _collect_report() -> dict:
    """Environment readiness, from the config file and the local cache.

    Deliberately not the same code the app uses: the app has to check whether D1
    holds a token row, which needs the Worker. This is the offline subset, for a
    terminal in a source checkout.
    """
    import sqlite3

    from spotify_core import config_file, paths

    client_id = bool(config_file.read_key("SPOTIFY_CLIENT_ID"))
    fernet_key = bool(config_file.read_key("TOKEN_ENCRYPT_KEY"))
    worker = bool(config_file.read_key("WORKER_URL") and config_file.read_key("WORKER_AUTH_TOKEN"))

    history_has_data = False
    if paths.history_db().exists():
        try:
            with sqlite3.connect(paths.history_db()) as conn:
                row = conn.execute("SELECT COUNT(*) FROM listening_history").fetchone()
                history_has_data = bool(row and row[0] > 0)
        except sqlite3.Error:
            pass

    checks = {
        "client_id": client_id,
        "fernet_key": fernet_key,
        "worker": worker,
        "history_has_data": history_has_data,
    }
    actions: list[str] = []
    if not client_id:
        actions.append("Set your Spotify Client ID in the desktop app's Setup page.")
    if not fernet_key:
        actions.append("Open the desktop app once — it generates TOKEN_ENCRYPT_KEY on sight.")
    if not worker:
        actions.append("Deploy Cloud sync from the desktop app's Setup page.")
    # Non-blocking: the export takes days to arrive, so an empty cache is a
    # normal state to be in.
    if worker and not history_has_data:
        actions.append("Run `spotify-mcp cloud pull` to fill the local cache from D1.")

    blocking = [a for a in actions if not a.startswith("Run `spotify-mcp cloud pull`")]
    return {
        "ready": not blocking,
        "checks": checks,
        "actions_needed": actions,
        "message": "All set." if not actions else f"{len(actions)} action(s) required.",
        "paths": paths.describe(),
    }


@app.command()
def doctor(
    json_out: Annotated[
        bool, typer.Option("--json", help="Print bare JSON (no colour) for machine callers.")
    ] = False,
) -> None:
    """Check environment readiness and print a JSON report. Exits 1 when not ready.

    The desktop app composes its own version of these checks (config-derived in
    `src-tauri/src/config.rs`, database-derived in `lib/config.ts`), which saved a
    ~1.7s process spawn per open and works in a packaged build. This is the
    terminal equivalent for a source checkout.
    """
    report = _collect_report()
    if json_out:
        print(json.dumps(report))
    else:
        console.print_json(json.dumps(report))
    raise typer.Exit(code=0 if report["ready"] else 1)


@app.command("config")
def config_show() -> None:
    """Print the resolved config paths and which settings have a value, as JSON.

    Read-only. `config get`, `config set` and `config keygen` used to live here;
    the desktop app called them and paid ~1.7s per invocation for a file read.
    The app owns config entirely now (`src-tauri/src/config.rs`), which is also
    the only way it can work in a packaged build with no `uv` on the machine.
    Writing from two places is what produced divergent config files before, so
    this side deliberately only reads.
    """
    from spotify_core import config_file, paths
    from spotify_core.config import load

    settings = load()
    print(
        json.dumps(
            {
                "config_path": str(paths.config_path()),
                "dev": settings.dev,
                "history_db_path": str(settings.history_db_path),
                # Booleans, never the secrets: this output is safe to paste.
                "configured": {
                    "client_id": bool(config_file.read_key("SPOTIFY_CLIENT_ID")),
                    "fernet_key": bool(config_file.read_key("TOKEN_ENCRYPT_KEY")),
                    "gemini": bool(settings.gemini_api_key),
                    "openai": bool(settings.openai_api_key),
                    "langfuse": settings.langfuse_configured,
                    "langsmith": bool(settings.langsmith_api_key),
                    "worker": bool(
                        config_file.read_key("WORKER_URL")
                        and config_file.read_key("WORKER_AUTH_TOKEN")
                    ),
                },
            }
        )
    )


@app.command("mcp-config")
def mcp_config() -> None:
    """Print the Claude Desktop MCP entry for this install, as JSON."""
    from spotify_mcp import claude_desktop as _cd

    print(json.dumps({
        "config_path": str(_cd.default_config_path()),
        "entry": {"mcpServers": {"spotify-mcp": _cd.build_entry()}},
    }))


cloud_app = typer.Typer(help="Talk to the Cloudflare Worker + D1 backend.")
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
    """Create D1, apply migrations, deploy the Worker (cron goes live), set secrets.

    Needs `node`/`npx` on PATH, which is why the desktop app cannot rely on this:
    an external user standing up their own Cloudflare stack will not have it. The
    app's Deploy button calls Cloudflare's REST API from Rust instead.
    """
    import sys

    from spotify_mcp import cloud

    # A Python traceback is noise the user cannot act on. Print the message,
    # keep the exit code.
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


@cloud_app.command("pull")
def cloud_pull() -> None:
    """Refresh the local SQLite cache from D1. Reads WORKER_* from the config file.

    The cache is what MCP and report generation read; `serve` also does this on
    startup, so this is for refreshing without launching anything.
    """
    from spotify_mcp import cloud

    raise typer.Exit(code=cloud.pull())


@app.command()
def serve() -> None:
    """Start the MCP server over stdio (invoked by Claude Desktop)."""
    import os

    from spotify_core import config_file, paths
    from spotify_core.logging import setup_mcp_logging

    paths.ensure_dirs()
    # Copy config into os.environ so env-based SDKs (e.g. Langfuse) see their
    # credentials. Real environment variables are never overridden.
    config_file.load_into_env()

    setup_mcp_logging(level=os.getenv("LOG_LEVEL", "DEBUG").upper())

    from spotify_mcp._mcp import main
    main()
