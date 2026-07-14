"""One-time migration: local SQLite (formerly R2-backed) -> D1 via the Worker.

Usage: uv run python scripts/migrate_r2_to_d1.py <history_db_path> <tokens_db_path>

Reads all listening_history rows and the encrypted token row from local SQLite
files and pushes them to D1 through the Worker's Bearer-token-gated API.
One-off cutover script — deleted after migration. No retries, no config
objects. Prints row counts only, never track names or tokens.
"""
import os
import sqlite3
import sys

from spotify_core.config import settings
from spotify_core.db.worker_client import WorkerClient
from spotify_core.spotify_client.token_store import export_encrypted_row

BATCH_SIZE = 200


def read_history_rows(history_db_path: str) -> list[dict]:
    conn = sqlite3.connect(history_db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT * FROM listening_history").fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]


def main() -> int:
    if len(sys.argv) != 3:
        print(
            "Usage: uv run python scripts/migrate_r2_to_d1.py "
            "<history_db_path> <tokens_db_path>",
            file=sys.stderr,
        )
        return 1

    history_db_path, tokens_db_path = sys.argv[1], sys.argv[2]

    worker_url = os.environ.get("WORKER_URL")
    worker_auth_token = os.environ.get("WORKER_AUTH_TOKEN")
    if not worker_url or not worker_auth_token:
        print("WORKER_URL / WORKER_AUTH_TOKEN not set", file=sys.stderr)
        return 1

    user_id = settings.spotify_user_id

    rows = read_history_rows(history_db_path)
    local_count = len(rows)
    print(f"local listening_history rows: {local_count}")

    with WorkerClient(worker_url, worker_auth_token) as worker:
        inserted_total = 0
        for start in range(0, local_count, BATCH_SIZE):
            batch = rows[start : start + BATCH_SIZE]
            inserted = worker.post_tracks(batch)
            inserted_total += inserted
            print(f"posted batch {start}-{start + len(batch)}: inserted {inserted}")
        print(f"total inserted: {inserted_total}")

        token_row = export_encrypted_row(tokens_db_path, user_id)
        if token_row is None:
            print(
                f"No token row found for user {user_id} in {tokens_db_path}",
                file=sys.stderr,
            )
            return 1
        worker.post_tokens(user_id, token_row)
        print(f"token row migrated for user {user_id}")

        remote_count = worker.get_tracks_count()

    print(f"remote listening_history rows: {remote_count}")
    if remote_count < local_count:
        print(
            f"WARNING: remote count {remote_count} < local count {local_count}",
            file=sys.stderr,
        )
        return 1

    print("migration OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
