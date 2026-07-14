"""Smoke tests for run_local_sync — WorkerClient is mocked, DB is a real temp file."""
from unittest.mock import MagicMock

import pytest

from spotify_core.db.local_sync import run_local_sync
from spotify_core.db.migrations import get_connection

TRACK_ROW = {
    "id": "row-1",
    "track_id": "spotify:track:abc",
    "track_name": "Song A",
    "artist_name": "Artist A",
    "album_name": "Album A",
    "played_at": "2024-01-15T08:30:00Z",
    "ms_played": 210000,
    "source": "api",
    "platform": None,
    "conn_country": None,
    "reason_start": None,
    "reason_end": None,
    "shuffle": None,
    "skipped": None,
}


@pytest.mark.unit
def test_run_local_sync_inserts_rows_and_updates_cursor(tmp_path):
    """Rows returned by the Worker land in listening_history and the meta cursor advances."""
    db_path = tmp_path / "history.db"
    worker = MagicMock()
    worker.get_tracks_since.return_value = [TRACK_ROW]
    worker.get_cursor.return_value = 1705307400000

    result = run_local_sync(db_path, worker)

    assert result["inserted"] == 1
    assert result["cursor_ms"] == 1705307400000

    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT track_id FROM listening_history WHERE id = 'row-1'"
        ).fetchone()
        assert row["track_id"] == "spotify:track:abc"

        meta_row = conn.execute(
            "SELECT value FROM meta WHERE key = 'last_sync_at_ms'"
        ).fetchone()
        assert meta_row["value"] == "1705307400000"
    finally:
        conn.close()

    worker.get_tracks_since.assert_called_once_with(0)


@pytest.mark.unit
def test_run_local_sync_idempotent_rerun_no_duplicates(tmp_path):
    """Re-running with the same rows does not create duplicate listening_history rows."""
    db_path = tmp_path / "history.db"
    worker = MagicMock()
    worker.get_tracks_since.return_value = [TRACK_ROW]
    worker.get_cursor.return_value = 1705307400000

    run_local_sync(db_path, worker)
    second_result = run_local_sync(db_path, worker)

    assert second_result["inserted"] == 0
    assert second_result["skipped_duplicated"] == 1

    conn = get_connection(db_path)
    try:
        count = conn.execute(
            "SELECT COUNT(*) AS c FROM listening_history"
        ).fetchone()["c"]
        assert count == 1
    finally:
        conn.close()
