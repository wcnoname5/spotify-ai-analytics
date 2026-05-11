"""Project setup workflow: init DBs, generate encryption key, run OAuth, import JSON history."""
import logging
import os
import re
from pathlib import Path

from spotify_core.config import settings
from spotify_core.db.migrations import init_ltm_db, init_tokens_db
from spotify_core.db.pipeline import import_json_to_db, init_history_db

logger = logging.getLogger(__name__)


def run_setup(
    user_id: str | None = None,
    db: str | None = None,
    tokens_db: str | None = None,
    ltm_db: str | None = None,
    json_dir: str | None = None,
) -> dict[str, bool | dict]:
    """Initialize DBs, run OAuth PKCE flow, and optionally import JSON history.

    Safe to call from MCP tools or CLI wrappers — logging must already be configured by
    the caller. Raises ValueError / RuntimeError on unrecoverable errors.

    Returns a summary dict with keys: 
        {
            "dbs_initialized": bool,
            "tokens_saved": bool,
            "json_imported": bool,
            "json_stats": dict | None
        }
    """
    user_id = user_id or settings.spotify_user_id
    db = db or str(settings.history_db_path)
    tokens_db = tokens_db or str(settings.tokens_db_path)
    ltm_db = ltm_db or str(settings.ltm_db_path)
    json_dir = json_dir or str(settings.spotify_data_path)

    if not user_id:
        raise ValueError(
            "SPOTIFY_USER_ID not set in environment and user_id was not provided"
        )

    # Step 1: Init all DBs (idempotent)
    logger.info("Initializing history DB at %s", db)
    init_history_db(db)

    logger.info("Initializing tokens DB at %s", tokens_db)
    init_tokens_db(tokens_db)

    logger.info("Initializing long-term memory DB at %s", ltm_db)
    init_ltm_db(ltm_db)

    # Step 2: OAuth
    from spotify_core.spotify_client.auth import run_pkce_flow
    from spotify_core.spotify_client.token_store import save_tokens

    client_id = os.environ.get("SPOTIFY_CLIENT_ID")
    fernet_key_str = os.environ.get("TOKEN_ENCRYPT_KEY")

    if not client_id:
        raise ValueError(
            "SPOTIFY_CLIENT_ID not set in environment.\n"
            "  → Create an app at https://developer.spotify.com/dashboard\n"
            "  → Copy the Client ID into your .env file as SPOTIFY_CLIENT_ID=..."
        )

    if not fernet_key_str:
        logger.warning("TOKEN_ENCRYPT_KEY not set - auto-generating a Fernet key")
        from cryptography.fernet import Fernet
        from spotify_core.logging import PROJECT_ROOT
        new_key = Fernet.generate_key().decode()
        env_path = PROJECT_ROOT / ".env"
        if env_path.exists():
            content = env_path.read_text()
            if "TOKEN_ENCRYPT_KEY=" in content:
                content = re.sub(r"TOKEN_ENCRYPT_KEY=\S*", f"TOKEN_ENCRYPT_KEY={new_key}", content)
            else:
                content += f"\nTOKEN_ENCRYPT_KEY={new_key}\n"
            env_path.write_text(content)
            logger.info("Auto-generated TOKEN_ENCRYPT_KEY saved to %s", env_path)
        else:
            logger.warning(
                "No .env file found - add this line manually: TOKEN_ENCRYPT_KEY=%s", new_key
            )
        fernet_key_str = new_key
        os.environ["TOKEN_ENCRYPT_KEY"] = new_key

    logger.info("Starting OAuth PKCE flow - your browser will open")
    token_data = run_pkce_flow(client_id=client_id)
    save_tokens(tokens_db, user_id, token_data, fernet_key_str.encode())
    logger.info("Tokens saved for user '%s' in %s", user_id, tokens_db)

    # Step 3: Import JSON (skipped silently if no files found)
    result: dict[str, bool | dict] = {"dbs_initialized": True, "tokens_saved": True, "json_imported": False}
    json_path = Path(json_dir)
    if json_path.exists() and list(json_path.rglob("Streaming*.json")):
        logger.info("Importing JSON from %s", json_dir)
        import_result = import_json_to_db(json_dir, db)
        logger.info(
            "JSON import complete: %d inserted, %d skipped duplicated, %d parse errors",
            import_result["inserted"],
            import_result["skipped_duplicated"],
            import_result["skipped_parse_error"],
        )
        result["json_imported"] = True
        result["json_stats"] = import_result
    else:
        logger.info(
            "No Streaming*.json files found in %s - skipping JSON import. "
            "Place your Streaming_History_Audio_*.json files there and re-run, or pass --json-dir.",
            json_dir,
        )

    logger.info("Setup complete. Next: uv run python scripts/sync_api.py")
    return result
