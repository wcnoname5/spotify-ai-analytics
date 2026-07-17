"""DEPRECATED manual fallback: sync recent plays from the Spotify API into D1.

The hourly cron now runs inside the Worker (worker/src/sync.ts); this script
is only run by the workflow_dispatch-only .github/workflows/sync.yml and will
be deleted once the Worker cron has proven itself.
Prints only row counts for logging.
"""
import os
import sys
import tempfile
from pathlib import Path

from spotify_core.config import get_client_id, get_fernet_key, settings
from spotify_core.db.pipeline import sync_api_to_worker
from spotify_core.db.worker_client import WorkerClient


def main() -> int:
    if not get_client_id() or not get_fernet_key():
        print("SPOTIFY_CLIENT_ID / TOKEN_ENCRYPT_KEY not set", file=sys.stderr)
        return 1

    worker_url = os.environ.get("WORKER_URL")
    worker_auth_token = os.environ.get("WORKER_AUTH_TOKEN")
    if not worker_url or not worker_auth_token:
        print("WORKER_URL / WORKER_AUTH_TOKEN not set", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory() as scratch_dir:
        tokens_scratch_db_path = str(Path(scratch_dir) / "tokens.db")
        with WorkerClient(worker_url, worker_auth_token) as worker:
            result = sync_api_to_worker(
                tokens_scratch_db_path=tokens_scratch_db_path,
                user_id=settings.spotify_user_id,
                client_id=get_client_id(),
                fernet_key=get_fernet_key(),
                worker=worker,
            )
    print(f"sync result: {result}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
