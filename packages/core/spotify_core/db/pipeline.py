"""Data pipeline: initialize, import, sync, and inspect the history DB."""
import hashlib
import logging
import sqlite3
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from spotify_dataloader.data_loader import SpotifyDataLoader
from .migrations import init_history_db as _migrations_init_history_db, get_connection
from ..spotify_client.client import SpotifyClient
from ..spotify_client.token_store import load_tokens

logger = logging.getLogger(__name__)

_CHEATSHEET = """
=== Spotify History DB — Quick Reference ===
DB: {db_path}

-- Recent 20 plays
SELECT played_at, track_name, artist_name, ms_played/1000 AS secs
FROM listening_history ORDER BY played_at DESC LIMIT 20;

-- Top artists by total listening time (minutes)
SELECT artist_name, SUM(ms_played)/60000 AS minutes
FROM listening_history GROUP BY artist_name ORDER BY minutes DESC LIMIT 10;

-- Top tracks by play count
SELECT track_name, artist_name, COUNT(*) AS plays
FROM listening_history GROUP BY track_id ORDER BY plays DESC LIMIT 10;

-- Listening by hour of day
SELECT strftime('%H', played_at) AS hour, COUNT(*) AS plays
FROM listening_history GROUP BY hour ORDER BY hour;

-- Row count and date range
SELECT COUNT(*) AS total, MIN(played_at) AS earliest, MAX(played_at) AS latest
FROM listening_history;

-- Sync cursor (last API sync timestamp in ms)
SELECT key, value FROM sync_state;
============================================
"""


def init_history_db(db_path: str) -> None:
    """Create data/history.db with listening_history and sync_state tables.

    Idempotent — safe to call multiple times.
    """
    _migrations_init_history_db(db_path)


def import_json_to_db(json_dir: str, db_path: str) -> dict:
    """Bulk load Streaming*.json files into listening_history.

    Returns:
        {"inserted": int, "skipped": int}
    """
    json_path = Path(json_dir)
    if not list(json_path.rglob("Streaming*.json")):
        logger.warning("No Streaming*.json files found in %s", json_dir)
        return {"inserted": 0, "skipped": 0}

    loader = SpotifyDataLoader(directory=json_path)
    df = loader.df
    if df is None or df.is_empty():
        return {"inserted": 0, "skipped": 0}

    inserted = skipped = 0
    conn = get_connection(db_path)
    try:
        with conn:  # BEGIN/COMMIT on success, ROLLBACK on exception
            for row in df.iter_rows(named=True):
                track_uri = row.get("track_uri") or ""
                ts_str = row.get("ts") or ""
                try:
                    played_dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    played_at_iso = played_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
                except (ValueError, AttributeError):
                    logger.warning("Skipping row with unparseable ts: %s", ts_str)
                    skipped += 1
                    continue

                row_id = hashlib.sha1(f"{track_uri}:{played_at_iso}".encode()).hexdigest()

                # Polars Duration("ms") columns become Python timedelta via iter_rows()
                ms_played_val = row.get("ms_played")
                ms_played_int = (
                    int(ms_played_val.total_seconds() * 1000)
                    if ms_played_val is not None
                    else None
                )

                cur = conn.execute(
                    "INSERT OR IGNORE INTO listening_history "
                    "(id, track_id, track_name, artist_name, album_name, "
                    " played_at, ms_played, source) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        row_id, track_uri,
                        row.get("track"), row.get("artist"), row.get("album"),
                        played_at_iso, ms_played_int, "json_import",
                    ),
                )
                if cur.rowcount > 0:
                    inserted += 1
                else:
                    skipped += 1
    finally:
        conn.close()

    logger.info("JSON import: %d inserted, %d skipped", inserted, skipped)
    return {"inserted": inserted, "skipped": skipped}


def sync_api_to_db(
    db_path: str,
    tokens_db_path: str,
    user_id: str,
    client_id: str,
    fernet_key: bytes,
) -> dict:
    """Fetch the 50 most recent plays from the Spotify API and upsert.

    Returns:
        {"inserted": int, "cursor_ms": int}
    """
    # Verify a token record exists — SpotifyClient handles auto-refresh internally
    token_data = load_tokens(tokens_db_path, user_id, fernet_key)
    if token_data is None:
        raise RuntimeError(
            "Run OAuth flow first: uv run python scripts/init_db.py --auth"
        )

    # Read current cursor from sync_state
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT value FROM sync_state WHERE key='last_played_at_ms'"
        ).fetchone()
        last_cursor_ms: Optional[int] = row["value"] if row else None
    finally:
        conn.close()

    # Fetch from Spotify API
    with SpotifyClient(tokens_db_path, user_id, client_id, fernet_key) as client:
        response = client.get_recently_played(limit=50, after=last_cursor_ms)

    items = response.get("items", [])
    if not items:
        logger.info("No new tracks from Spotify API")
        return {"inserted": 0, "cursor_ms": last_cursor_ms or 0}

    inserted = skipped = 0
    new_cursor_ms = last_cursor_ms or 0

    conn = get_connection(db_path)
    try:
        with conn:  # BEGIN/COMMIT on success, ROLLBACK on exception
            for item in items:
                track = item.get("track", {})
                track_uri = track.get("uri", "")
                played_at_str = item.get("played_at", "")

                try:
                    played_dt = datetime.fromisoformat(played_at_str.replace("Z", "+00:00"))
                    played_at_iso = played_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
                    played_at_ms = int(played_dt.timestamp() * 1000)
                except (ValueError, AttributeError):
                    logger.warning("Skipping item with unparseable played_at: %s", played_at_str)
                    skipped += 1
                    continue

                row_id = hashlib.sha1(f"{track_uri}:{played_at_iso}".encode()).hexdigest()
                artists = track.get("artists") or []
                artist_name = artists[0]["name"] if artists else None
                album_name = (track.get("album") or {}).get("name")
                # duration_ms is total track length; recently-played API doesn't return actual play time
                ms_played = track.get("duration_ms")

                cur = conn.execute(
                    "INSERT OR IGNORE INTO listening_history "
                    "(id, track_id, track_name, artist_name, album_name, "
                    " played_at, ms_played, source) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        row_id, track_uri, track.get("name"),
                        artist_name, album_name,
                        played_at_iso, ms_played, "api",
                    ),
                )
                if cur.rowcount > 0:
                    inserted += 1
                    new_cursor_ms = max(new_cursor_ms, played_at_ms)
                else:
                    skipped += 1

            if new_cursor_ms > (last_cursor_ms or 0):
                conn.execute(
                    "INSERT OR REPLACE INTO sync_state (key, value) "
                    "VALUES ('last_played_at_ms', ?)",
                    (new_cursor_ms,),
                )
    finally:
        conn.close()

    logger.info("API sync: %d inserted, %d skipped, cursor=%d", inserted, skipped, new_cursor_ms)
    return {"inserted": inserted, "cursor_ms": new_cursor_ms}


def open_inspect_shell(db_path: str) -> None:
    """Print SQL cheatsheet then launch sqlite3 interactive shell."""
    print(_CHEATSHEET.format(db_path=db_path))

    sqliterc = ".mode column\n.headers on\n"
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".sqliterc", delete=False
    ) as f:
        f.write(sqliterc)
        tmp_rc = f.name

    try:
        subprocess.run(["sqlite3", db_path, "-init", tmp_rc], check=False)
    finally:
        Path(tmp_rc).unlink(missing_ok=True)
