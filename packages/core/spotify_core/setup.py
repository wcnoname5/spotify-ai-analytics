"""Project setup workflow: init DBs, generate encryption key, run OAuth, import JSON history."""
import os
from loguru import logger
from pathlib import Path

from spotify_core.config import settings, get_client_id, get_fernet_key
from spotify_core.db.migrations import init_ltm_db, init_tokens_db
from spotify_core.db.pipeline import import_json_to_db, init_history_db

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
    logger.info("Initializing history DB at {}", db)
    init_history_db(db)

    logger.info("Initializing tokens DB at {}", tokens_db)
    init_tokens_db(tokens_db)

    logger.info("Initializing long-term memory DB at {}", ltm_db)
    init_ltm_db(ltm_db)

    # Step 2: OAuth
    from spotify_core.spotify_client.auth import run_pkce_flow
    from spotify_core.spotify_client.token_store import save_tokens

    client_id = get_client_id()
    fernet_key = get_fernet_key()

    if not client_id:
        raise ValueError(
            "SPOTIFY_CLIENT_ID not set in environment.\n"
            "  → Create an app at https://developer.spotify.com/dashboard\n"
            "  → Copy the Client ID into your .env file as SPOTIFY_CLIENT_ID=..."
        )

    if not fernet_key:
        logger.warning("TOKEN_ENCRYPT_KEY not set - auto-generating a Fernet key")
        from cryptography.fernet import Fernet
        from spotify_core import env_file as _env_file, paths

        new_key = Fernet.generate_key().decode()
        _env_file.upsert(paths.env_file(), "TOKEN_ENCRYPT_KEY", new_key)
        logger.info("Auto-generated TOKEN_ENCRYPT_KEY saved to {}", paths.env_file())

        fernet_key = new_key.encode()
        os.environ["TOKEN_ENCRYPT_KEY"] = new_key

    logger.info("Starting OAuth PKCE flow - your browser will open")
    token_data = run_pkce_flow(client_id=client_id)
    save_tokens(tokens_db, user_id, token_data, fernet_key)
    logger.info("Tokens saved for user {!r} in {}", user_id, tokens_db)

    # Step 3: Import JSON (skipped silently if no files found)
    result: dict[str, bool | dict] = {"dbs_initialized": True, "tokens_saved": True, "json_imported": False}
    json_path = Path(json_dir)
    if json_path.exists() and list(json_path.rglob("Streaming*.json")):
        logger.info("Importing JSON from {}", json_dir)
        import_result = import_json_to_db(json_dir, db)
        logger.info(
            "JSON import complete: {} inserted, {} skipped duplicated, {} parse errors",
            import_result["inserted"],
            import_result["skipped_duplicated"],
            import_result["skipped_parse_error"],
        )
        result["json_imported"] = True
        result["json_stats"] = import_result
    else:
        logger.info(
            "No Streaming*.json files found in {} - skipping JSON import. "
            "Place your Streaming_History_Audio_*.json files there and re-run, or pass --json-dir.",
            json_dir,
        )

    logger.info("Setup complete. Next: uv run python scripts/sync_api.py")
    return result
