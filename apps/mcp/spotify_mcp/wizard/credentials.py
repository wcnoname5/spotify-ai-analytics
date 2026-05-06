"""Wizard steps: persist Client ID and ensure a Fernet key exists."""
import os

from cryptography.fernet import Fernet
from rich.console import Console

from spotify_core import env_file, paths


def persist_client_id(raw: str) -> None:
    """Trim, validate non-empty, warn (don't reject) on suspicious shape, persist."""
    value = raw.strip()
    if not value:
        raise ValueError("Client ID must not be empty.")
    env_file.upsert(paths.env_file(), "SPOTIFY_CLIENT_ID", value)
    os.environ["SPOTIFY_CLIENT_ID"] = value


def looks_like_client_id(value: str) -> bool:
    """Soft heuristic: 32-char hex. False is a warning, not a rejection."""
    return len(value) == 32 and all(c in "0123456789abcdef" for c in value.lower())


def prompt_client_id(console: Console) -> str:
    """Prompt the user for their Client ID and persist it. Returns the value."""
    while True:
        value = console.input("[bold]Paste your Spotify Client ID:[/bold] ").strip()
        if not value:
            console.print("[red]Client ID is required.[/red]")
            continue
        if not looks_like_client_id(value):
            console.print(
                "[yellow]Heads up — that doesn't look like the usual 32-char hex Client ID, "
                "but proceeding anyway. If OAuth fails, double-check the value.[/yellow]"
            )
        persist_client_id(value)
        return value


def ensure_fernet_key(console: Console) -> str:
    """Read existing TOKEN_ENCRYPT_KEY, or generate one and persist.

    Never overwrites an existing key — regenerating would orphan all stored tokens.
    """
    existing = env_file.read_key(paths.env_file(), "TOKEN_ENCRYPT_KEY")
    if existing:
        os.environ["TOKEN_ENCRYPT_KEY"] = existing
        return existing
    new_key = Fernet.generate_key().decode()
    env_file.upsert(paths.env_file(), "TOKEN_ENCRYPT_KEY", new_key)
    os.environ["TOKEN_ENCRYPT_KEY"] = new_key
    console.print(
        f"[yellow]Generated a new encryption key and saved it to {paths.env_file()}.\n"
        "Do NOT delete this file — losing the key makes stored tokens unrecoverable.[/yellow]"
    )
    return new_key
