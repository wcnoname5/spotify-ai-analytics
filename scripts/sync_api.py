"""Sync recent Spotify plays from the API into history.db."""
import argparse
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from spotify_core.db.pipeline import sync_api_to_db


def main():
    parser = argparse.ArgumentParser(
        description="Fetch recent plays from Spotify API and upsert into history.db"
    )
    parser.add_argument(
        "--user-id", required=True,
        help="Spotify user ID (same value used during --auth)"
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

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)
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
