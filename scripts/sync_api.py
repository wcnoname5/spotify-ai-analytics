"""
Sync recent Spotify plays from the API into history.db. 
NOTE: This sync need to run routinely (e.g. via cron) to keep the database up to date, as the Spotify API only provides access to the most recent ~50 plays.
"""
import argparse
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from _logging import setup_logging
from spotify_core.db.pipeline import sync_api_to_db
from spotify_core.config import settings


def main():
    parser = argparse.ArgumentParser(
        description="Fetch recent plays from Spotify API and upsert into history.db"
    )
    parser.add_argument(
        "--user-id",
        default=settings.spotify_user_id,
        help="Spotify user ID (defaults to SPOTIFY_USER_ID from .env)",
    )
    parser.add_argument(
        "--db", default="data/history.db",
        help="Path to history.db (default: data/history.db)"
    )
    parser.add_argument(
        "--tokens-db", default="data/tokens.db",
        help="Path to tokens.db (default: data/tokens.db)"
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logger = logging.getLogger(__name__)
    if not args.user_id:
        logger.error("SPOTIFY_USER_ID not set in environment and --user-id was not provided")
        sys.exit(1)

    setup_logging(args.verbose)
    logger = logging.getLogger(__name__)

    client_id = os.environ.get("SPOTIFY_CLIENT_ID")
    fernet_key_str = os.environ.get("TOKEN_ENCRYPT_KEY")
    if not client_id:
        logger.error("SPOTIFY_CLIENT_ID not set in environment")
        sys.exit(1)
    if not fernet_key_str:
        logger.error("TOKEN_ENCRYPT_KEY not set in environment")
        sys.exit(1)

    logger.info("Syncing recent plays for user '%s'", args.user_id)
    result = sync_api_to_db(
        db_path=args.db,
        tokens_db_path=args.tokens_db,
        user_id=args.user_id,
        client_id=client_id,
        fernet_key=fernet_key_str.encode(),
    )
    logger.info(
        "Inserted %d rows, cursor updated to %d ms",
        result["inserted"], result["cursor_ms"]
    )


if __name__ == "__main__":
    main()
