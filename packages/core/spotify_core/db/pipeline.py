"""Data pipeline: initialize and sync the history DB.

`import_json_to_db` used to live here. It read a Spotify data export with Polars
(156 MB of dependencies to parse JSON) and wrote to the *local* SQLite, which was
backwards: local SQLite is a disposable mirror of D1, so an import that only
landed there was lost on any machine change. The desktop app now parses the
export in TS (`packages/shared-ts/export.ts`) and posts it to the Worker.

`open_inspect_shell` went too — it shelled out to a `sqlite3` binary that a
packaged user has no reason to have.
"""
import hashlib
import sqlite3
from loguru import logger
from datetime import datetime, timezone
from typing import Optional

from .migrations import init_history_db as _migrations_init_history_db, init_tokens_db, get_connection
from ..spotify_client.client import SpotifyClient
from ..spotify_client.token_store import load_tokens, export_encrypted_row, import_encrypted_row


def init_history_db(db_path: str) -> None:
    """Create data/history.db with listening_history and sync_state tables.

    Idempotent — safe to call multiple times.
    """
    _migrations_init_history_db(db_path)


def parse_api_item(item: dict, source: str = "api") -> Optional[dict]:
    """Parse a single Spotify API recently-played item into a row dict.

    Pure function — no DB connection required, so it can be reused by
    non-DB-coupled sync paths (e.g. a cron worker without a live connection).

    Input:
        item: dict representing a single play from Spotify API /me/player/recently-played response.
        source: str indicating the source of the data ("api" or "json_import") to populate the source column in the DB.

    Returns:
        dict with keys: id, track_id, track_name, artist_name, album_name,
        played_at, ms_played, source, played_at_ms.
        None if played_at is missing/unparseable.
    """
    track = item.get("track", {})
    track_uri = track.get("uri", "")
    played_at_str = item.get("played_at", "")

    try:
        played_dt = datetime.fromisoformat(played_at_str.replace("Z", "+00:00"))
        played_at_iso = played_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        played_at_ms = int(played_dt.timestamp() * 1000)
    except (ValueError, AttributeError):
        # Unparseable date — skip this item but don't fail the whole batch
        logger.warning("Skipping item with unparseable played_at: {}", played_at_str)
        return None

    row_id = hashlib.sha1(f"{track_uri}:{played_at_iso}".encode()).hexdigest()
    artists = track.get("artists") or []
    artist_name = artists[0]["name"] if artists else None
    album_name = (track.get("album") or {}).get("name")
    ms_played = track.get("duration_ms")

    return {
        "id": row_id,
        "track_id": track_uri,
        "track_name": track.get("name"),
        "artist_name": artist_name,
        "album_name": album_name,
        "played_at": played_at_iso,
        "ms_played": ms_played,
        "source": source,
        "played_at_ms": played_at_ms,
    }


def _insert_item_from_api_response(conn, item: dict, source: str = "api"):
    """Insert a single Spotify API recently-played item into the DB.
    Input:
        conn: SQLite connection with listening_history table.
        item: dict representing a single play from Spotify API /me/player/recently-played response.
        source: str indicating the source of the data ("api" or "json_import") to populate the source column in the DB.

    Returns:
        (inserted: bool, duplicated: bool, skipped_due_to_unparseable_date: bool, played_at_ms: Optional[int])
    """
    row = parse_api_item(item, source=source)
    if row is None:
        return False, False, True, None

    cur = conn.execute(
        "INSERT OR IGNORE INTO listening_history "
        "(id, track_id, track_name, artist_name, album_name, "
        " played_at, ms_played, source, "
        " platform, conn_country, reason_start, reason_end, shuffle, skipped) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, NULL, NULL)",
        (
            row["id"], row["track_id"], row["track_name"],
            row["artist_name"], row["album_name"],
            row["played_at"], row["ms_played"], row["source"],
        ),
    )
    # inserted if rowcount > 0, otherwise it was a duplicate and skipped
    if cur.rowcount > 0:
        return True, False, False, row["played_at_ms"]
    return False, True, False, row["played_at_ms"]


def sync_api_to_db(
    db_path: str,
    tokens_db_path: str,
    user_id: str,
    client_id: str,
    fernet_key: bytes,
) -> dict:
    """Fetch the 50 most recent plays from the Spotify API and upsert.

    Returns:
        {"inserted": int, "skipped_duplicated": int, "skipped_parse_error": int, "cursor_ms": int}
    """
    # Verify a token record exists — SpotifyClient handles auto-refresh internally
    token_data = load_tokens(tokens_db_path, user_id, fernet_key)
    if token_data is None:
        raise RuntimeError(
            f"No OAuth tokens found for user '{user_id}'. "
            "Run the OAuth flow first: spotify-mcp reauth"
        )

    # Read current cursor from sync_state
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT value FROM sync_state WHERE key='last_played_at_ms'"
        ).fetchone()
        db_last_cursor: Optional[int] = row["value"] if row else None
    except Exception as e:
        logger.error("Error occurred while fetching sync cursor from sync_state DB: {}", e)
    finally:
        conn.close()

    # Fetch from Spotify API
    with SpotifyClient(tokens_db_path, user_id, client_id, fernet_key) as client:
        response = client.get_recently_played(limit=50, after=db_last_cursor)

    items = response.get("items", [])
    if not items:
        logger.info("No new tracks from Spotify API")
        return {"inserted": 0, "skipped_duplicated": 0, "skipped_parse_error": 0, "cursor_ms": db_last_cursor or 0}

    inserted = skipped_duplicated = skipped_parse_error = 0
    new_cursor_ms = db_last_cursor or 0

    conn = get_connection(db_path)
    try:
        with conn:  # BEGIN/COMMIT on success, ROLLBACK on exception
            for item in items:
                inserted_flag, is_duplicate, is_unparseable, played_at_ms = _insert_item_from_api_response(
                    conn, item, source="api"
                )
                if is_unparseable:
                    skipped_parse_error += 1
                    continue
                if inserted_flag:
                    inserted += 1
                    if played_at_ms:
                        new_cursor_ms = max(new_cursor_ms, played_at_ms)
                elif is_duplicate:
                    skipped_duplicated += 1

            # Update sync_state cursor if we've advanced beyond the last cursor in the DB
            if new_cursor_ms > (db_last_cursor or 0):
                conn.execute(
                    "INSERT OR REPLACE INTO sync_state (key, value) "
                    "VALUES ('last_played_at_ms', ?)",
                    (new_cursor_ms,),
                )
    except Exception as e:
        logger.error("Error occurred during API sync: {}", e)
    finally:
        conn.close()

    logger.info("API sync: {} inserted, {} skipped duplicated, {} skipped parse errors, cursor={}", inserted, skipped_duplicated, skipped_parse_error, new_cursor_ms)
    return {"inserted": inserted, "skipped_duplicated": skipped_duplicated, "skipped_parse_error": skipped_parse_error, "cursor_ms": new_cursor_ms}
