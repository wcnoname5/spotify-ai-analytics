"""Bulk-import Spotify JSON history exports into history.db."""
import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from spotify_core.db.pipeline import import_json_to_db


def main():
    parser = argparse.ArgumentParser(
        description="Bulk-import Streaming*.json files into history.db"
    )
    parser.add_argument(
        "--dir", default="data/spotify_history",
        help="Directory containing Streaming*.json files (default: data/spotify_history)"
    )
    parser.add_argument(
        "--db", default="data/history.db",
        help="Path to history.db (default: data/history.db)"
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)
    logger = logging.getLogger(__name__)

    logger.info("Importing JSON from %s into %s", args.dir, args.db)
    result = import_json_to_db(args.dir, args.db)
    logger.info("Inserted %d rows, skipped %d duplicates", result["inserted"], result["skipped"])


if __name__ == "__main__":
    main()
