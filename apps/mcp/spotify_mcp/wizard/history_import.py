"""Wizard step: optional history import.

UX rule: never make the user type a path. Primary UX is a native folder
picker (tkinter filedialog). On headless systems where Tk can't open a
window, falls back to scanning cwd. Power users can pass
`spotify-mcp import-history --from <path>` to skip the prompt entirely.
"""
from loguru import logger
from pathlib import Path
from typing import Literal, Optional

from rich.console import Console
from rich.panel import Panel

from spotify_core import paths

_REQUEST_BANNER = (
    "[bold]Recommended:[/bold] request your full Spotify listening history from Spotify Privacy.\n"
    "It contains years of plays vs. only the last 50 from the live API.\n"
    "Request at https://www.spotify.com/account/privacy/ — arrives by email in ~5 days."
)


def scan_dir(directory: Path) -> list[Path]:
    """Return all Streaming_History_Audio_*.json files in a directory (non-recursive)."""
    return sorted(Path(directory).glob("Streaming_History_Audio_*.json"))


def _tk_askdirectory() -> str:
    """Open a native folder-picker dialog. Returns the selected path or "" if cancelled.

    Isolated for monkeypatching. Raises whatever tkinter raises if Tk cannot
    be initialised (e.g. no DISPLAY) — caller is expected to handle.
    """
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()  # hide the empty root window
    try:
        return filedialog.askdirectory(title="Select your Spotify history export folder")
    finally:
        root.destroy()


def pick_dir_via_gui() -> Optional[Path]:
    """Try to open the GUI folder picker. Returns the selected Path, or None on:

    - tkinter import failure (missing _tkinter)
    - Tk init failure (no display, no X server)
    - user cancellation (askdirectory returns "")
    """
    try:
        selected = _tk_askdirectory()
    except Exception:
        return None
    if not selected:
        return None
    return Path(selected)


def _prompt_choice(console: Console) -> Literal["import", "sync", "skip"]:
    console.print(
        "\n[bold]Choose history source:[/bold]\n"
        "  [1] Import a Spotify JSON export (opens folder picker)\n"
        "  [2] Sync the most recent 50 plays from the live API (instant, partial)\n"
        "  [3] Skip — I'll do this later"
    )
    while True:
        choice = console.input("Select [1/2/3]: ").strip()
        if choice == "1":
            return "import"
        if choice == "2":
            return "sync"
        if choice == "3":
            return "skip"
        console.print("[red]Please enter 1, 2, or 3.[/red]")


def _confirm_use_cwd(console: Console, files: list[Path]) -> bool:
    if not files:
        console.print(
            "[yellow]GUI picker unavailable and no Streaming_History_Audio_*.json files in the "
            "current directory. Drop the files into the current folder (or `cd` to where they are) "
            "and re-run `spotify-mcp setup`. Or use `spotify-mcp import-history` directly."
            "[/yellow]"
        )
        return False
    console.print(
        f"[yellow]GUI picker unavailable. Found {len(files)} file(s) in the current directory:[/yellow]"
    )
    for f in files:
        console.print(f"  • {f.name}")
    answer = console.input("Import these? [y/N] ").strip().lower()
    return answer == "y"


def _do_import(console: Console, files: list[Path]) -> None:
    from spotify_core.db.pipeline import import_json_to_db

    if not files:
        return

    directory = files[0].parent
    console.print(f"Importing {len(files)} file(s) from {directory} into {paths.history_db()}...")
    result = import_json_to_db(str(directory), str(paths.history_db()))
    console.print(
        f"[green]Imported {result['inserted']} rows.[/green]  "
        f"Duplicates skipped: {result['skipped_duplicated']}, "
        f"parse errors: {result['skipped_parse_error']}"
    )


def import_history(console: Console, import_path: Path | None = None) -> None:
    """Import history from a path, or open the folder picker when no path is provided."""
    if import_path is not None:
        from spotify_core.db.pipeline import import_json_to_db, init_history_db

        # Promptless entry (the Tauri Setup page) never runs the wizard's
        # init step, so this path must initialize for itself. Idempotent.
        init_history_db(str(paths.history_db()))
        result = import_json_to_db(str(import_path), str(paths.history_db()))
        console.print(
            f"[green]Imported {result['inserted']} rows from {import_path}.[/green]"
        )
        return

    selected_dir = pick_dir_via_gui()
    if selected_dir is not None:
        files = scan_dir(selected_dir)
        if not files:
            console.print(
                f"[yellow]No Streaming_History_Audio_*.json files found in {selected_dir}.[/yellow]"
            )
            return
        _do_import(console, files)
        return

    cwd_files = scan_dir(Path.cwd())
    if _confirm_use_cwd(console, cwd_files):
        _do_import(console, cwd_files)


def _do_sync_recent(console: Console) -> None:
    """Sync the last 50 plays via the Spotify API."""
    from spotify_core.db.pipeline import init_history_db

    init_history_db(str(paths.history_db()))
    try:
        from spotify_core.db.pipeline import sync_api_to_db
        from spotify_mcp.config import (
            DB_PATH,
            DEFAULT_USER_ID,
            TOKENS_DB,
            get_client_id,
            get_fernet_key,
        )
        client_id = get_client_id()
        fernet_key = get_fernet_key()
        final_user_id = DEFAULT_USER_ID
    except ImportError as exc:
        console.print(
            f"[yellow]{exc}[/yellow]"
        )
        return
    
    result = sync_api_to_db(
            db_path=DB_PATH,
            tokens_db_path=TOKENS_DB,
            user_id=final_user_id,
            client_id=client_id,
            fernet_key=fernet_key,
        )
    console.print(f"[green]✓ Synced {result['inserted']} new plays (cursor: {result['cursor_ms']} ms)[/green]")



def run_step(console: Console, import_path: Path | None = None) -> None:
    """Either import from a fixed path (--import flag) or run the interactive choice."""
    if import_path is not None:
        import_history(console=console, import_path=import_path)
        return

    console.print(Panel.fit(_REQUEST_BANNER, title="Step 5 / 6: Load listening history"))

    choice = _prompt_choice(console)
    if choice == "skip":
        console.print("Skipping history load. Re-run `spotify-mcp setup` any time.")
        return
    if choice == "sync":
        _do_sync_recent(console)
        return

    import_history(console=console)
