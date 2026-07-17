"""Seed D1 from the local SQLite data via the Worker (one-shot, rerun-safe).

Called by scripts/setup_cloud.sh (step 5) — pushes two things:

- The encrypted Spotify token row from the local tokens.db. Skipped if D1
  already has one `--force` to overwrite

- All local listening_history rows (wizard OAuth + optional JSON import).

To seed history from some other SQLite file (e.g. a downloaded backup),
place it at the local history path (`spotify-mcp path` shows it) first.

Prints row counts only — never track names or tokens.

--tokens-only skips the history part (e.g. re-seeding just the token row
after a reauth).

Usage:
    WORKER_URL=... WORKER_AUTH_TOKEN=... uv run python scripts/seed_d1.py [--force] [--tokens-only]
"""
import os
import sqlite3
import sys
from pathlib import Path

from spotify_core.config import settings
from spotify_core.db.worker_client import WorkerClient
from spotify_core.spotify_client.token_store import export_encrypted_row

BATCH_SIZE = 200


def seed_tokens(worker: WorkerClient, user_id: str) -> bool:
    """Push the local encrypted token row. Returns False if D1 ends up without one."""
    if "--force" not in sys.argv and worker.get_tokens(user_id) is not None:
        print(f"tokens: D1 already has a row for user '{user_id}' — skipping (--force to overwrite).")
        return True

    row = export_encrypted_row(settings.tokens_db_path, user_id)
    if row is None:
        print(
            f"tokens: no row for user '{user_id}' in {settings.tokens_db_path} — "
            "run the OAuth flow first (spotify-mcp setup)",
            file=sys.stderr,
        )
        return False

    worker.post_tokens(user_id, row)
    print(f"tokens: pushed encrypted row for user '{user_id}'.")
    return True


def seed_history(worker: WorkerClient) -> bool:
    """Push local listening_history rows D1 doesn't have yet. Returns success."""
    db_path = Path(settings.history_db_path)
    if not db_path.exists():
        print(f"history: no local DB at {db_path} — nothing to seed.")
        return True

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in conn.execute("SELECT * FROM listening_history")]
    finally:
        conn.close()
    
    # skip insert if D1 has more rows.
    local_count = len(rows)
    remote_count = worker.get_tracks_count()
    print(f"history: {local_count} local rows, {remote_count} in D1.")
    if remote_count >= local_count:
        print("history: D1 is already up to date — skipping.")
        return True

    inserted_total = 0
    for start in range(0, local_count, BATCH_SIZE):
        batch = rows[start : start + BATCH_SIZE]
        inserted_total += worker.post_tracks(batch)
        print(f"history: posted rows {start}-{start + len(batch)}, inserted so far {inserted_total}")

    remote_count = worker.get_tracks_count()
    print(f"history: D1 now has {remote_count} rows.")
    if remote_count < local_count:
        print(
            f"history: WARNING remote count {remote_count} < local count {local_count}",
            file=sys.stderr,
        )
        return False
    return True


def main() -> int:
    worker_url = os.environ.get("WORKER_URL")
    worker_auth_token = os.environ.get("WORKER_AUTH_TOKEN")
    if not worker_url or not worker_auth_token:
        print("WORKER_URL / WORKER_AUTH_TOKEN not set", file=sys.stderr)
        return 1

    user_id = os.environ.get("SPOTIFY_USER_ID", "default")
    with WorkerClient(worker_url, worker_auth_token) as worker:
        tokens_ok = seed_tokens(worker, user_id)
        history_ok = True if "--tokens-only" in sys.argv else seed_history(worker)

    return 0 if (tokens_ok and history_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
