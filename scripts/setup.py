"""One-command setup: init DB, OAuth, import JSON history.

Recommended flow:
    1. uv run python scripts/setup.py
     (add --json-dir if your Streaming*.json files are not in data/spotify_history)
    2. uv run python scripts/sync_api.py
     (fills gap from JSON end to present; run again anytime to stay up to date)

Re-running this script is safe — DB init is idempotent and JSON re-import skips duplicates.
"""
import argparse
import logging
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from _logging import setup_logging
from spotify_core.db.pipeline import init_history_db, import_json_to_db
from spotify_core.db.migrations import init_ltm_db, init_tokens_db
from spotify_core.config import settings


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Set up Spotify history DB: init → OAuth → (optional) import JSON. "
            "Run sync_api.py afterwards to fill the gap from JSON end to present."
        )
    )
    parser.add_argument(
        "--user-id",
        default=settings.spotify_user_id,
        help="Your Spotify username (defaults to SPOTIFY_USER_ID from .env)",
    )
    parser.add_argument("--db", default=str(settings.history_db_path),
                        help=f"Path to history.db (default: {settings.history_db_path})")
    parser.add_argument("--tokens-db", default=str(settings.tokens_db_path),
                        help=f"Path to tokens.db (default: {settings.tokens_db_path})")
    parser.add_argument("--ltm-db", default=str(settings.ltm_db_path),
                        help=f"Path to ltm.db (default: {settings.ltm_db_path})")
    parser.add_argument("--json-dir", default=str(settings.spotify_data_path),
                        help="Directory containing Streaming*.json files "
                             f"(default: {settings.spotify_data_path}; step skipped if no files found)")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    setup_logging(args.verbose)
    logger = logging.getLogger(__name__)

    if not args.user_id:
        logger.error("SPOTIFY_USER_ID not set in environment and --user-id was not provided")
        sys.exit(1)

    # Step 1: Init all DBs (idempotent)
    logger.info("Initializing history DB at %s", args.db)
    init_history_db(args.db)

    logger.info("Initializing tokens DB at %s", args.tokens_db)
    init_tokens_db(args.tokens_db)

    logger.info("Initializing long-term memory DB at %s", args.ltm_db)
    init_ltm_db(args.ltm_db)

    # Step 2: OAuth
    from spotify_core.spotify_client.auth import run_pkce_flow
    from spotify_core.spotify_client.token_store import save_tokens

    client_id = os.environ.get("SPOTIFY_CLIENT_ID")
    fernet_key_str = os.environ.get("TOKEN_ENCRYPT_KEY")

    if not client_id:
        logger.error(
            "SPOTIFY_CLIENT_ID not set in environment.\n"
            "  → Create an app at https://developer.spotify.com/dashboard\n"
            "  → Copy the Client ID into your .env file as SPOTIFY_CLIENT_ID=..."
        )
        sys.exit(1)

    if not fernet_key_str:
        logger.warning("TOKEN_ENCRYPT_KEY not set — auto-generating a Fernet key")
        from cryptography.fernet import Fernet
        new_key = Fernet.generate_key().decode()
        env_path = Path(__file__).resolve().parent.parent / ".env"
        if env_path.exists():
            content = env_path.read_text()
            if "TOKEN_ENCRYPT_KEY=" in content:
                content = re.sub(r"TOKEN_ENCRYPT_KEY=\S*", f"TOKEN_ENCRYPT_KEY={new_key}", content)
            else:
                content += f"\nTOKEN_ENCRYPT_KEY={new_key}\n"
            env_path.write_text(content)
            logger.info("Auto-generated TOKEN_ENCRYPT_KEY saved to %s", env_path)
        else:
            logger.warning("No .env file found — add this line manually: TOKEN_ENCRYPT_KEY=%s", new_key)
        fernet_key_str = new_key
        os.environ["TOKEN_ENCRYPT_KEY"] = new_key

    logger.info("Starting OAuth PKCE flow — your browser will open")
    token_data = run_pkce_flow(client_id=client_id)
    save_tokens(args.tokens_db, args.user_id, token_data, fernet_key_str.encode())
    logger.info("Tokens saved for user '%s' in %s", args.user_id, args.tokens_db)

    # Step 3: Import JSON (skipped silently if no files found)
    json_path = Path(args.json_dir)
    if json_path.exists() and list(json_path.rglob("Streaming*.json")):
        logger.info("Importing JSON from %s", args.json_dir)
        result = import_json_to_db(args.json_dir, args.db)
        logger.info(
            "JSON import complete: %d inserted, %d skipped duplicated, %d parse errors",
            result["inserted"], result["skipped_duplicated"], result["skipped_parse_error"],
        )
    else:
        logger.info(
            "No Streaming*.json files found in %s — skipping JSON import. "
            "Place your Streaming_History_Audio_*.json files there and re-run, or pass --json-dir.",
            args.json_dir,
        )

    logger.info("Setup complete. Next: uv run python scripts/sync_api.py")


if __name__ == "__main__":
    main()
