"""Refresh the local SQLite cache from D1 via the Worker.

Local SQLite is a pull-only sync cache of D1 (never written to
independently) — MCP and report generation read it. Prints only row counts.
"""
import os
import sys

from spotify_core.config import settings
from spotify_core.db.local_sync import run_local_sync
from spotify_core.db.worker_client import WorkerClient


def main() -> int:
    worker_url = os.environ.get("WORKER_URL")
    worker_auth_token = os.environ.get("WORKER_AUTH_TOKEN")
    if not worker_url or not worker_auth_token:
        print("WORKER_URL / WORKER_AUTH_TOKEN not set", file=sys.stderr)
        return 1

    with WorkerClient(worker_url, worker_auth_token) as worker:
        result = run_local_sync(settings.history_db_path, worker)

    print(f"local sync result: {result}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
