"""Setup wizard orchestration — composes resumable steps."""
from __future__ import annotations

from rich.console import Console

from spotify_core import paths

from . import (
    claude_desktop,
    credentials,
    history_import,
    langfuse_keys,
    llm_keys,
    oauth_step,
    spotify_app,
    state,
)


def run_wizard(
    setup_claude_desktop: bool = False,
    console: Console | None = None,
) -> None:
    """Run the setup wizard, skipping any already-completed step."""
    console = console or Console()
    paths.ensure_dirs()

    if not state.has_client_id():
        spotify_app.run_step(console=console)
        credentials.prompt_client_id(console)

    if not state.has_fernet_key():
        credentials.ensure_fernet_key(console=console)

    if not state.dbs_initialized():
        from spotify_core.db.migrations import init_history_db, init_ltm_db, init_tokens_db

        init_history_db(paths.history_db())
        init_tokens_db(paths.tokens_db())
        init_ltm_db(paths.ltm_db())
        console.print("[green]Databases initialized.[/green]")

    if not state.tokens_valid():
        oauth_step.run_oauth(console=console, force=False)

    if not state.history_has_data():
        history_import.run_step(console=console, import_path=None)

    llm_keys.run_step(console=console)
    langfuse_keys.run_step(console=console)

    claude_desktop.run_step(console=console, install=setup_claude_desktop)
    console.print("\n[bold green]Setup complete.[/bold green]")
