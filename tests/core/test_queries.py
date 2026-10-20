"""Tests for the db/queries.py SQL analytics layer."""
import sqlite3
import pytest
from spotify_core.db.errors import HistoryNotInitializedError
from spotify_core.db.queries import (
    get_top_artists,
    get_top_tracks,
    get_listening_summary,
)


@pytest.fixture()
def seeded_db(history_db):
    return history_db([
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


class TestGetTopArtists:
    def test_returns_sorted_by_time(self, seeded_db):
        results = get_top_artists(seeded_db, limit=10)
        # Artist X: 200k + 150k + 200k = 550k ms = 9 mins
        # Artist Y: 300k ms = 5 mins
        assert results[0]["artist_name"] == "Artist X"
        assert results[0]["total_mins"] == 9
        assert results[1]["artist_name"] == "Artist Y"

    def test_limit_respected(self, seeded_db):
        results = get_top_artists(seeded_db, limit=1)
        assert len(results) == 1

    def test_date_filter_start(self, seeded_db):
        # Only plays from Feb onwards: Artist X (200k = 3 min) vs Artist Y (300k = 5 min)
        results = get_top_artists(seeded_db, start_date="2024-02-01")
        artists = {r["artist_name"]: r["total_mins"] for r in results}
        assert "Artist X" in artists
        assert artists["Artist X"] == 3
        assert artists["Artist Y"] == 5

    def test_date_filter_end(self, seeded_db):
        # Only plays up to Jan 31: Artist X (200k + 150k = 350k = 5 min), no Artist Y
        results = get_top_artists(seeded_db, end_date="2024-01-31")
        artists = {r["artist_name"]: r["total_mins"] for r in results}
        assert "Artist Y" not in artists
        assert artists["Artist X"] == 5

    def test_empty_db(self, history_db):
        assert get_top_artists(history_db()) == []


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

    def test_empty_db(self, history_db):
        assert get_top_tracks(history_db()) == []


class TestGetListeningSummary:
    def test_counts_match(self, seeded_db):
        summary = get_listening_summary(seeded_db)
        assert summary["total_plays"] == 4
        assert summary["unique_artists"] == 2
        # track_id "1" used twice — unique tracks = 3 (id 1, 2, 3)
        assert summary["unique_tracks"] == 3
        assert summary["earliest_played_at"] == "2024-01-10T12:00:00Z"
        assert summary["latest_played_at"] == "2024-02-10T12:00:00Z"

    def test_empty_db(self, history_db):
        summary = get_listening_summary(history_db())
        assert summary["total_plays"] == 0
        assert summary["earliest_played_at"] is None

    def test_date_filter_start(self, seeded_db):
        summary = get_listening_summary(seeded_db, start_date="2024-02-01")
        assert summary["total_plays"] == 2

    def test_date_filter_end(self, seeded_db):
        summary = get_listening_summary(seeded_db, end_date="2024-01-31")
        assert summary["total_plays"] == 2

    def test_total_mins_played(self, seeded_db):
        summary = get_listening_summary(seeded_db)
        # 200k + 150k + 300k + 200k = 850k ms = 14 min
        assert summary["total_mins_played"] == 14

    def test_avg_mins_per_play(self, seeded_db):
        summary = get_listening_summary(seeded_db)
        # 850k / 4 = 212500 ms = 3 min (truncated)
        assert summary["avg_mins_per_play"] == 3

    def test_skip_rate_no_skips(self, seeded_db):
        summary = get_listening_summary(seeded_db)
        # All plays >= 150k ms — no skips
        assert summary["skip_rate"] == pytest.approx(0.0)

    def test_skip_rate_with_short_plays(self, history_db):
        db = history_db([
            {"id": "1", "track_name": "Full", "artist_name": "A",
             "played_at": "2024-01-10T12:00:00Z", "ms_played": 200_000},
            {"id": "2", "track_name": "Skip", "artist_name": "A",
             "played_at": "2024-01-11T12:00:00Z", "ms_played": 10_000},
        ])
        summary = get_listening_summary(db)
        assert summary["skip_rate"] == pytest.approx(0.5)

    def test_volume_stats_scoped_by_date_filter(self, seeded_db):
        # Only Jan plays: 200k + 150k = 350k ms = 5 min, 2 plays, avg 175k ms = 2 min
        summary = get_listening_summary(seeded_db, end_date="2024-01-31")
        assert summary["total_mins_played"] == 5
        assert summary["avg_mins_per_play"] == 2


class TestHistoryNotInitializedError:
    """Analytics queries should raise HistoryNotInitializedError when the DB
    file is missing or the listening_history table has not been created."""

    def test_missing_db_file_raises(self, tmp_path):
        db = str(tmp_path / "nope.db")
        with pytest.raises(HistoryNotInitializedError):
            get_top_artists(db)

    def test_missing_table_raises(self, tmp_path):
        db = str(tmp_path / "no_table.db")
        # Create the file but no listening_history table.
        sqlite3.connect(db).close()
        with pytest.raises(HistoryNotInitializedError):
            get_top_artists(db)
        with pytest.raises(HistoryNotInitializedError):
            get_top_tracks(db)
        with pytest.raises(HistoryNotInitializedError):
            get_listening_summary(db)
