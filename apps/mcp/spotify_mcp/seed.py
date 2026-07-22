"""Push local SQLite data up to D1 through the Worker. Rerun-safe.

Moved here from scripts/seed_d1.py (since deleted) so packaging bundles one exe
-- the same rule that put every setup step behind a `spotify-mcp` subcommand.
Reached via `spotify-mcp cloud seed`, and from `cloud deploy`'s final step.

Prints row counts only — never track names or tokens.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from spotify_core.config import settings
from spotify_core.db.worker_client import WorkerClient
from spotify_core.spotify_client.token_store import export_encrypted_row

BATCH_SIZE = 200


def local_token_row(user_id: str):
    """The local encrypted token row, or None if there isn't one.

    A tokens.db that was never initialised has no `spotify_tokens` table at all,
    which raises rather than returning None — same situation from the caller's
    point of view: this machine has not authorized Spotify yet.
    """
    try:
        return export_encrypted_row(settings.tokens_db_path, user_id)
    except sqlite3.OperationalError:
        return None


def seed_tokens(worker: WorkerClient, user_id: str, force: bool = False) -> bool:
    """Push the local encrypted token row. Returns False if D1 ends up without one."""
    if not force and worker.get_tokens(user_id) is not None:
        print(f"tokens: D1 already has a row for user '{user_id}' — skipping (--force to overwrite).")
        return True

    row = local_token_row(user_id)
    if row is None:
        print(
            f"tokens: no row for user '{user_id}' in {settings.tokens_db_path} — "
            "run the OAuth flow first (spotify-mcp reauth)",
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
