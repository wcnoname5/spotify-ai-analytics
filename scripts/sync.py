"""CI entry point: sync recent plays from the Spotify API into history.db.

Run by .github/workflows/sync.yml with SPOTIFY_MCP_DATA_DIR=./data, so DB
paths resolve to the checkout's data/ directory (populated from R2 before
this script runs).
Prints only row counts — Actions logs on a public repo are world-readable.
"""
import sys

from spotify_core.config import get_client_id, get_fernet_key, settings
from spotify_core.db.pipeline import sync_api_to_db


def main() -> int:
    if not get_client_id() or not get_fernet_key():
        print("SPOTIFY_CLIENT_ID / TOKEN_ENCRYPT_KEY not set", file=sys.stderr)
        return 1
    result = sync_api_to_db(
        db_path=str(settings.history_db_path),
        tokens_db_path=str(settings.tokens_db_path),
        user_id=settings.spotify_user_id,
        client_id=get_client_id(),
        fernet_key=get_fernet_key(),
    )
    print(f"sync result: {result}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
