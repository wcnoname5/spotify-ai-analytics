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
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from spotify_core.config import settings
from spotify_core.setup import run_setup

logger = logging.getLogger(__name__)


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
    parser.add_argument(
        "--db",
        default=str(settings.history_db_path),
        help=f"Path to history.db (default: {settings.history_db_path})",
    )
    parser.add_argument(
        "--tokens-db",
        default=str(settings.tokens_db_path),
        help=f"Path to tokens.db (default: {settings.tokens_db_path})",
    )
    parser.add_argument(
        "--ltm-db",
        default=str(settings.ltm_db_path),
        help=f"Path to ltm.db (default: {settings.ltm_db_path})",
    )
    parser.add_argument(
        "--json-dir",
        default=str(settings.spotify_data_path),
        help=(
            "Directory containing Streaming*.json files "
            f"(default: {settings.spotify_data_path}; step skipped if no files found)"
        ),
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    from spotify_core.logging import setup_logging
    level = logging.DEBUG if args.verbose else logging.getLevelNamesMapping().get(
        os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO
    )
    setup_logging(log_name="setup", level=level)

    if not args.user_id:
        logger.error("SPOTIFY_USER_ID not set in environment and --user-id was not provided")
        sys.exit(1)

    try:
        run_setup(
            user_id=args.user_id,
            db=args.db,
            tokens_db=args.tokens_db,
            ltm_db=args.ltm_db,
            json_dir=args.json_dir,
        )
    except Exception as exc:
        logger.error("Setup failed: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
