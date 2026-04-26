"""Tests for db/queries.py SQL analytics layer (Stage 6)."""
import pytest
from spotify_core.db.migrations import init_history_db
from spotify_core.db.migrations import get_connection
from spotify_core.db.queries import get_top_artists, get_top_tracks, get_listening_summary


def _seed_db(db_path: str, rows: list[dict]) -> None:
    """Insert test rows into listening_history."""
    conn = get_connection(db_path)
    with conn:
        for r in rows:
            conn.execute(
                "INSERT OR IGNORE INTO listening_history "
                "(id, track_id, track_name, artist_name, album_name, played_at, ms_played, source) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    r["id"], r.get("track_id", r["id"]),
                    r.get("track_name"), r.get("artist_name"),
                    r.get("album_name"), r["played_at"],
                    r.get("ms_played"), r.get("source", "json_import"),
                ),
            )
    conn.close()


@pytest.fixture()
def seeded_db(tmp_path):
    db = str(tmp_path / "history.db")
    init_history_db(db)
    _seed_db(db, [
        {"id": "1", "track_name": "Song A", "artist_name": "Artist X",
         "played_at": "2024-01-10T12:00:00Z", "ms_played": 200_000},
        {"id": "2", "track_name": "Song B", "artist_name": "Artist X",
         "played_at": "2024-01-11T12:00:00Z", "ms_played": 150_000},
        {"id": "3", "track_name": "Song C", "artist_name": "Artist Y",
         "played_at": "2024-02-01T12:00:00Z", "ms_played": 300_000},
        {"id": "4", "track_name": "Song A", "artist_name": "Artist X",
         "track_id": "1",  # duplicate track_id — same track replayed
         "played_at": "2024-02-10T12:00:00Z", "ms_played": 200_000},
    ])
    return db


class TestGetTopArtists:
    def test_returns_sorted_by_ms(self, seeded_db):
        results = get_top_artists(seeded_db, limit=10)
        # Artist X: 200k + 150k + 200k = 550k ms
        # Artist Y: 300k ms
        assert results[0]["artist_name"] == "Artist X"
        assert results[0]["total_ms"] == 550_000
        assert results[1]["artist_name"] == "Artist Y"

    def test_limit_respected(self, seeded_db):
        results = get_top_artists(seeded_db, limit=1)
        assert len(results) == 1

    def test_date_filter_start(self, seeded_db):
        # Only plays from Feb onwards: Artist X (200k) vs Artist Y (300k)
        results = get_top_artists(seeded_db, start_date="2024-02-01")
        artists = {r["artist_name"]: r["total_ms"] for r in results}
        assert "Artist X" in artists
        assert artists["Artist X"] == 200_000
        assert artists["Artist Y"] == 300_000

    def test_date_filter_end(self, seeded_db):
        # Only plays up to Jan 31: Artist X (200k + 150k = 350k), no Artist Y
        results = get_top_artists(seeded_db, end_date="2024-01-31")
        artists = {r["artist_name"]: r["total_ms"] for r in results}
        assert "Artist Y" not in artists
        assert artists["Artist X"] == 350_000

    def test_empty_db(self, tmp_path):
        db = str(tmp_path / "empty.db")
        init_history_db(db)
        results = get_top_artists(db)
        assert results == []


class TestGetTopTracks:
    def test_returns_sorted_by_play_count(self, seeded_db):
        results = get_top_tracks(seeded_db, limit=10)
        # Song A has track_id "1", played twice
        top = results[0]
        assert top["track_name"] == "Song A"
        assert top["play_count"] == 2

    def test_limit_respected(self, seeded_db):
        results = get_top_tracks(seeded_db, limit=1)
        assert len(results) == 1

    def test_date_filter(self, seeded_db):
        results = get_top_tracks(seeded_db, start_date="2024-02-01")
        names = [r["track_name"] for r in results]
        assert "Song B" not in names  # Song B played Jan 11

    def test_empty_db(self, tmp_path):
        db = str(tmp_path / "empty.db")
        init_history_db(db)
        assert get_top_tracks(db) == []


class TestGetListeningSummary:
    def test_counts_match(self, seeded_db):
        summary = get_listening_summary(seeded_db)
        assert summary["total_plays"] == 4
        assert summary["unique_artists"] == 2
        # track_id "1" used twice — unique tracks = 3 (id 1, 2, 3)
        assert summary["unique_tracks"] == 3
        assert summary["earliest_played_at"] == "2024-01-10T12:00:00Z"
        assert summary["latest_played_at"] == "2024-02-10T12:00:00Z"

    def test_empty_db(self, tmp_path):
        db = str(tmp_path / "empty.db")
        init_history_db(db)
        summary = get_listening_summary(db)
        assert summary["total_plays"] == 0
        assert summary["earliest_played_at"] is None
