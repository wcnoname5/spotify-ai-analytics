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
def test_run_local_sync_inserts_rows_and_advances_cursor(tmp_path):
    """Rows returned by the Worker land in listening_history; cursor = MAX(played_at)."""
    db_path = tmp_path / "history.db"
    worker = MagicMock()
    worker.get_tracks_since.return_value = [TRACK_ROW]
    worker.get_reports_since.return_value = []

    result = run_local_sync(db_path, worker)

    assert result["inserted"] == 1
    assert result["cursor"] == "2024-01-15T08:30:00Z"

    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT track_id FROM listening_history WHERE id = 'row-1'"
        ).fetchone()
        assert row["track_id"] == "spotify:track:abc"
    finally:
        conn.close()

    # First sync on an empty cache asks from the epoch.
    worker.get_tracks_since.assert_called_once_with("1970-01-01T00:00:00Z")


@pytest.mark.unit
def test_run_local_sync_second_run_asks_from_max_played_at(tmp_path):
    """A re-run passes the cache's MAX(played_at) as the since cursor."""
    db_path = tmp_path / "history.db"
    worker = MagicMock()
    worker.get_tracks_since.return_value = [TRACK_ROW]
    worker.get_reports_since.return_value = []

    run_local_sync(db_path, worker)
    worker.get_tracks_since.return_value = []
    second_result = run_local_sync(db_path, worker)

    assert second_result["inserted"] == 0
    assert second_result["cursor"] == "2024-01-15T08:30:00Z"
    worker.get_tracks_since.assert_called_with("2024-01-15T08:30:00Z")

    conn = get_connection(db_path)
    try:
        count = conn.execute(
            "SELECT COUNT(*) AS c FROM listening_history"
        ).fetchone()["c"]
        assert count == 1
    finally:
        conn.close()
