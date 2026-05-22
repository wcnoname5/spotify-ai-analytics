"""Resumability state checks for the setup wizard.

Each check reads the *current* state from disk/env and returns a bool. Used by
the wizard to skip already-completed steps and by `spotify-mcp doctor`.
"""
import os
from loguru import logger
from pathlib import Path

from spotify_core import env_file, paths


def _client_id_value() -> str:
    """Prefer process env, fall back to <config_dir>/.env."""
    val = os.environ.get("SPOTIFY_CLIENT_ID")
    if val:
        return val
    return env_file.read_key(paths.env_file(), "SPOTIFY_CLIENT_ID") or ""


def _fernet_key_value() -> str:
    val = os.environ.get("TOKEN_ENCRYPT_KEY")
    if val:
        return val
    return env_file.read_key(paths.env_file(), "TOKEN_ENCRYPT_KEY") or ""


def has_client_id() -> bool:
    return bool(_client_id_value().strip())


def has_fernet_key() -> bool:
    return bool(_fernet_key_value().strip())


def dbs_initialized() -> bool:
    """Both history and tokens DBs exist with a known table."""
    import sqlite3

    for db_path, table in (
        (paths.history_db(), "listening_history"),
        (paths.tokens_db(), "spotify_tokens"),
    ):
        if not db_path.exists():
            return False
        try:
            with sqlite3.connect(db_path) as conn:
                conn.execute(f"SELECT 1 FROM {table} LIMIT 0")
        except sqlite3.Error:
            return False
    if not paths.ltm_db().exists():
        return False
    try:
        with sqlite3.connect(paths.ltm_db()) as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
            ).fetchone()
            return bool(row and row[0] > 0)
    except sqlite3.Error:
        return False


def tokens_valid() -> bool:
    """Tokens row exists for the default user, decrypts cleanly, and has a refresh_token.

    Does NOT check expiry of the access token (refresh handles that at runtime)
    and does NOT ping Spotify (slow, network-dependent).
    """
    if not has_fernet_key():
        return False
    if not paths.tokens_db().exists():
        return False
    try:
        from spotify_core.spotify_client.token_store import load_tokens

        # Read user_id from env/env-file; fall back to "default".
        user_id = (
            os.environ.get("SPOTIFY_USER_ID")
            or env_file.read_key(paths.env_file(), "SPOTIFY_USER_ID")
            or "default"
        )
        tokens = load_tokens(
            paths.tokens_db(),
            user_id,
            _fernet_key_value().encode(),
        )
        return bool(tokens and tokens.get("refresh_token"))
    except Exception as e:
        logger.debug("tokens_valid check failed: %s", e)
        return False


def history_has_data() -> bool:
    import sqlite3

    if not paths.history_db().exists():
        return False
    try:
        with sqlite3.connect(paths.history_db()) as conn:
            row = conn.execute("SELECT COUNT(*) FROM listening_history").fetchone()
            return bool(row and row[0] > 0)
    except sqlite3.Error:
        return False


def collect_report() -> dict:
    """Build a `setup_check`-style report from the live filesystem state."""
    checks = {
        "client_id": has_client_id(),
        "fernet_key": has_fernet_key(),
        "dbs_initialized": dbs_initialized(),
        "tokens_valid": tokens_valid(),
        "history_has_data": history_has_data(),
    }
    actions: list[str] = []
    if not checks["client_id"]:
        actions.append("Set SPOTIFY_CLIENT_ID — run `spotify-mcp setup`")
    if not checks["fernet_key"]:
        actions.append("Generate TOKEN_ENCRYPT_KEY — run `spotify-mcp setup`")
    if not checks["dbs_initialized"]:
        actions.append("Initialize databases — run `spotify-mcp setup`")
    if not checks["tokens_valid"]:
        actions.append("Authorize with Spotify — run `spotify-mcp setup` (or `spotify-mcp reauth`)")
    if checks["dbs_initialized"] and not checks["history_has_data"]:
        actions.append(
            "Load history — run `spotify-mcp setup` (option 1: import full export, "
            "or option 2: sync recent 50 plays)"
        )

    blocking = [a for a in actions if "Load history" not in a]
    return {
        "ready": not blocking,
        "checks": checks,
        "actions_needed": actions,
        "message": "All set." if not actions else f"{len(actions)} action(s) required.",
    }
