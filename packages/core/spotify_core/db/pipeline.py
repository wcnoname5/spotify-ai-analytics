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

        {"inserted": int, "duplicated": int, "unparseable_dates": int}
    """
    json_path = Path(json_dir)
    if not list(json_path.rglob("Streaming*.json")):
        logger.warning("No Streaming*.json files found in %s", json_dir)
        return {"inserted": 0, "duplicated": 0, "unparseable_dates": 0}

    loader = SpotifyDataLoader(directory=json_path)
    df = loader.df
    if df is None or df.is_empty():
        return {"inserted": 0, "duplicated": 0, "unparseable_dates": 0}

    inserted = duplicated = unparseable_dates = 0
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
                    unparseable_dates += 1
                    continue
                row_id = hashlib.sha1(f"{track_uri}:{played_at_iso}".encode()).hexdigest()

                # Polars Duration("ms") columns become Python timedelta via iter_rows()
                ms_played_val = row.get("ms_played")
                ms_played_int = (
                    int(ms_played_val.total_seconds() * 1000)
                    if ms_played_val is not None
                    else None
                )

                shuffle_val = row.get("shuffle")
                skipped_val = row.get("skipped")

                cur = conn.execute(
                    "INSERT OR IGNORE INTO listening_history "
                    "(id, track_id, track_name, artist_name, album_name, "
                    " played_at, ms_played, source, "
                    " platform, conn_country, reason_start, reason_end, shuffle, skipped) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        row_id, track_uri,
                        row.get("track"), row.get("artist"), row.get("album"),
                        played_at_iso, ms_played_int, "json_import",
                        row.get("platform"), row.get("conn_country"),
                        row.get("reason_start"), row.get("reason_end"),
                        int(shuffle_val) if shuffle_val is not None else None,
                        int(skipped_val) if skipped_val is not None else None,
                    ),
                )
                if cur.rowcount > 0:
                    inserted += 1
                else:
                    duplicated += 1
    finally:
        conn.close()

    logger.info("JSON import: %d inserted, %d duplicated, %d with unparseable dates", inserted, duplicated, unparseable_dates)
    return {"inserted": inserted, "duplicated": duplicated, "unparseable_dates": unparseable_dates}


def _insert_item_from_api_response(conn, item: dict, source: str = "api"):
    """Insert a single Spotify API recently-played item into the DB.

    Returns:
    (inserted: bool, duplicated: bool, skipped_due_to_unparseable_date: bool, played_at_ms: Optional[int])
    """
    track = item.get("track", {})
    track_uri = track.get("uri", "")
    played_at_str = item.get("played_at", "")

    try:
        played_dt = datetime.fromisoformat(played_at_str.replace("Z", "+00:00"))
        played_at_iso = played_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        played_at_ms = int(played_dt.timestamp() * 1000)
    except (ValueError, AttributeError):
        logger.warning("Skipping item with unparseable played_at: %s", played_at_str)
        return False, False, True, None

    row_id = hashlib.sha1(f"{track_uri}:{played_at_iso}".encode()).hexdigest()
    artists = track.get("artists") or []
    artist_name = artists[0]["name"] if artists else None
    album_name = (track.get("album") or {}).get("name")
    ms_played = track.get("duration_ms")

    cur = conn.execute(
        "INSERT OR IGNORE INTO listening_history "
        "(id, track_id, track_name, artist_name, album_name, "
        " played_at, ms_played, source, "
        " platform, conn_country, reason_start, reason_end, shuffle, skipped) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, NULL, NULL)",
        (
            row_id, track_uri, track.get("name"),
            artist_name, album_name,
            played_at_iso, ms_played, source,
        ),
    )
    # inserted if rowcount > 0, otherwise it was a duplicate and skipped
    if cur.rowcount > 0:
        return True, False, False, played_at_ms
    return False, True, False, played_at_ms


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
    # This serve as a proxy to conn_contry for api sync items since API doesn't return country info in recently played endpoint
    # we can use the user's country as a proxy for all API items
    country = client.get_current_user().get("country")
    try:
        with conn:  # BEGIN/COMMIT on success, ROLLBACK on exception
            for item in items:
                inserted_flag, duplicated, skipped_unparseable, played_at_ms = _insert_item_from_api_response(
                    conn, item, source="api"
                )
                if skipped_unparseable:
                    skipped += 1
                    continue
                if inserted_flag:
                    inserted += 1
                    if played_at_ms:
                        new_cursor_ms = max(new_cursor_ms, played_at_ms)
                else:
                    if duplicated:
                        duplicated += 1
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

    logger.info("API sync: %d inserted, %d duplicated, %d skipped, cursor=%d", inserted, duplicated, skipped, new_cursor_ms)
    return {"inserted": inserted, "duplicated": duplicated, "skipped": skipped, "cursor_ms": new_cursor_ms}


def sync_api_up_to_date(
    db_path: str,
    tokens_db_path: str,
    user_id: str,
    client_id: str,
    fernet_key: bytes,
    max_calls: int = 10,
) -> dict:
    """Backfill history by paging backward from now until the json_import anchor.

    Uses the ``before`` cursor on ``GET /me/player/recently-played`` to walk
    backward in time, stopping when the oldest fetched item is at or before the
    latest json_import record.  When no json_import anchor exists (empty DB or
    synced before any JSON load) it runs for ``max_calls`` iterations and stops.

    Returns:
        {"inserted": int, "cursor_ms": int}
    """
    token_data = load_tokens(tokens_db_path, user_id, fernet_key)
    if token_data is None:
        raise RuntimeError(
            "Run OAuth flow first: uv run python scripts/init_db.py --auth"
        )

    # Anchor: latest played_at from json_import — stop backfill once we reach it.
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT MAX(played_at) FROM listening_history WHERE source='json_import'"
        ).fetchone()
        anchor_str: Optional[str] = row[0] if row else None
    finally:
        conn.close()

    # The timestamp to stop backfilling at (the json_import anchor) in ms since epoch. If null, backfill until max_calls is reached.
    stop_at_ms: Optional[int] = None
    if anchor_str:
        try:
            anchor_dt = datetime.fromisoformat(anchor_str.replace("Z", "+00:00"))
            stop_at_ms = int(anchor_dt.timestamp() * 1000)
        except (ValueError, AttributeError):
            logger.warning("Could not parse json_import anchor '%s' — no stop cursor", anchor_str)

    inserted = skipped = 0
    new_cursor_ms = 0
    # start from current timstamp
    before_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

    with SpotifyClient(tokens_db_path, user_id, client_id, fernet_key) as client:
        for call_num in range(max_calls):
            response = client.get_recently_played(limit=50, before=before_ms)
            items = response.get("items", [])
            if not items:
                logger.info("No more items from Spotify API after %d call(s)", call_num + 1)
                break
            # This serve as a proxy to conn_contry for api sync items since API doesn't return country info in recently played endpoint
            # we can use the user's country as a proxy for all API items
            country = client.get_current_user().get("country")
            conn = get_connection(db_path)
            try:
                with conn:
                    for item in items:
                        inserted_flag, duplicated, skipped_unparseable, played_at_ms = _insert_item_from_api_response(
                            conn, item, source="api"
                        )
                        if skipped_unparseable:
                            skipped += 1
                            continue
                        if inserted_flag:
                            inserted += 1
                            if played_at_ms:
                                new_cursor_ms = max(new_cursor_ms, played_at_ms)
                        else:
                            if duplicated:
                                duplicated += 1
                            else:
                                skipped += 1
                            skipped += 1
            finally:
                conn.close()

            # The cursor to use as key to find the previous page of items.
            before_ms = response.get("cursors", {}).get("before")
            # changet type to int
            before_ms = int(before_ms) if before_ms else None

            if stop_at_ms is not None and before_ms <= stop_at_ms:
                logger.info("Reached json_import anchor at call %d — backfill complete", call_num + 1)
                break

    if new_cursor_ms > 0:
        conn = get_connection(db_path)
        try:
            with conn:
                conn.execute(
                    "INSERT OR REPLACE INTO sync_state (key, value) "
                    "VALUES ('last_played_at_ms', ?)",
                    (new_cursor_ms,),
                )
        finally:
            conn.close()

    logger.info("Backfill: %d inserted, %d duplicated, %d skipped, cursor=%d", inserted, duplicated, skipped, new_cursor_ms)
    return {"inserted": inserted, "duplicated": duplicated, "skipped": skipped, "cursor_ms": new_cursor_ms}



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
