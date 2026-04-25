"""Open an interactive sqlite3 shell for history.db with a SQL cheatsheet."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from spotify_core.db.pipeline import open_inspect_shell


def main():
    parser = argparse.ArgumentParser(
        description="Inspect history.db interactively via sqlite3"
    )
    parser.add_argument(
        "--db", default="data/history.db",
        help="Path to history.db (default: data/history.db)"
    )
    args = parser.parse_args()
    open_inspect_shell(args.db)


if __name__ == "__main__":
    main()
