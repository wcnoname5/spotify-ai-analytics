"""Wizard step: run the OAuth PKCE flow and store encrypted tokens."""
import os

from rich.console import Console

from spotify_core import paths
from spotify_core.config import settings
from spotify_core.spotify_client import auth as _auth
from spotify_core.spotify_client import token_store as _token_store

from spotify_mcp.wizard import state, spotify_app


def run_oauth(console: Console, force: bool = False) -> None:
    """Run the PKCE flow if needed; persist encrypted tokens to tokens.db.

    Skips when ``state.tokens_valid()`` is True and ``force`` is False.
    """
    if not force and state.tokens_valid():
        console.print("[green]Existing Spotify tokens are valid — skipping OAuth.[/green]")
        return

    client_id = os.environ.get("SPOTIFY_CLIENT_ID", "").strip()
    fernet_key = os.environ.get("TOKEN_ENCRYPT_KEY", "").strip()
    if not client_id:
        raise RuntimeError("SPOTIFY_CLIENT_ID not set — run earlier wizard steps first.")
    if not fernet_key:
        raise RuntimeError("TOKEN_ENCRYPT_KEY not set — run earlier wizard steps first.")

    console.print("[bold]Opening browser for Spotify login...[/bold]")
    token_data = _auth.run_pkce_flow(client_id=client_id, port=spotify_app.OAUTH_PORT)
    _token_store.save_tokens(paths.tokens_db(), settings.spotify_user_id, token_data, fernet_key.encode())
    console.print("[green]Spotify authorization complete.[/green]")
