"""Tests for db/queries.py SQL analytics layer (Stage 6)."""
import sqlite3
import pytest
from spotify_core.db.errors import HistoryDBError, HistoryNotInitializedError
from spotify_core.db.migrations import init_history_db
from spotify_core.db.migrations import get_connection
from spotify_core.db.queries import (
    get_top_artists,
    get_top_tracks,
    get_listening_summary,
    get_listening_patterns,
    get_recent_plays,
)


def _seed_db(db_path: str, rows: list[dict]) -> None:
    """Insert test rows into listening_history."""
    conn = get_connection(db_path)
    with conn:
        for r in rows:
            conn.execute(
                "INSERT OR IGNORE INTO listening_history "
                "(id, track_id, track_name, artist_name, album_name, played_at, ms_played, source, conn_country) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    r["id"], r.get("track_id", r["id"]),
                    r.get("track_name"), r.get("artist_name"),
                    r.get("album_name"), r["played_at"],
                    r.get("ms_played"), r.get("source", "json_import"),
                    r.get("conn_country"),
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

    def test_skip_rate_with_short_plays(self, tmp_path):
        db = str(tmp_path / "history.db")
        init_history_db(db)
        _seed_db(db, [
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


class TestGetListeningPatterns:
    def test_returns_expected_keys(self, seeded_db):
        patterns = get_listening_patterns(seeded_db)
        for key in ("peak_hour", "peak_day_of_week", "most_active_date", "avg_plays_per_day"):
            assert key in patterns

    def test_peak_hour(self, seeded_db):
        patterns = get_listening_patterns(seeded_db)
        # All plays at T12:00:00Z → hour 12
        assert patterns["peak_hour"] == 12

    def test_peak_day_of_week(self, seeded_db):
        patterns = get_listening_patterns(seeded_db)
        # Jan 11 and Feb 1 are both Thursday → peak
        assert patterns["peak_day_of_week"] == "Thursday"

    def test_most_active_date_is_valid(self, seeded_db):
        patterns = get_listening_patterns(seeded_db)
        assert patterns["most_active_date"] is not None
        # Should be a YYYY-MM-DD string
        assert len(patterns["most_active_date"]) == 10

    def test_avg_plays_per_day(self, seeded_db):
        patterns = get_listening_patterns(seeded_db)
        # 4 plays across 4 distinct days → 1.0
        assert patterns["avg_plays_per_day"] == pytest.approx(1.0)

    def test_date_filter_scopes_patterns(self, seeded_db):
        patterns = get_listening_patterns(seeded_db, end_date="2024-01-31")
        # Only Jan 10 + Jan 11 → 2 plays / 2 days = 1.0
        assert patterns["avg_plays_per_day"] == pytest.approx(1.0)

    def test_empty_db_returns_none_values(self, tmp_path):
        db = str(tmp_path / "empty.db")
        init_history_db(db)
        patterns = get_listening_patterns(db)
        assert patterns["peak_hour"] is None
        assert patterns["peak_day_of_week"] is None
        assert patterns["most_active_date"] is None
        assert patterns["avg_plays_per_day"] is None


@pytest.fixture()
def seeded_db_tw(tmp_path):
    """DB seeded with TW (+8) country — two plays at T16:00:00Z on 2024-01-10.

    UTC view:  2024-01-10 (Wednesday), hour 16
    TW local:  2024-01-11 (Thursday),  hour 00
    """
    db = str(tmp_path / "history.db")
    init_history_db(db)
    _seed_db(db, [
        {"id": "1", "track_name": "A", "artist_name": "X",
         "played_at": "2024-01-10T16:00:00Z", "ms_played": 200_000, "conn_country": "TW"},
        {"id": "2", "track_name": "B", "artist_name": "X",
         "played_at": "2024-01-10T16:01:00Z", "ms_played": 150_000, "conn_country": "TW"},
    ])
    return db


class TestGetListeningPatternsTimezone:
    def test_peak_hour_uses_local_time(self, seeded_db_tw):
        patterns = get_listening_patterns(seeded_db_tw)
        # UTC hour = 16, TW local (+8) = 0
        assert patterns["peak_hour"] == 0

    def test_peak_day_uses_local_time(self, seeded_db_tw):
        patterns = get_listening_patterns(seeded_db_tw)
        # UTC: 2024-01-10 = Wednesday; TW local: 2024-01-11 = Thursday
        assert patterns["peak_day_of_week"] == "Thursday"

    def test_most_active_date_uses_local_date(self, seeded_db_tw):
        patterns = get_listening_patterns(seeded_db_tw)
        # UTC date: 2024-01-10; TW local date: 2024-01-11
        assert patterns["most_active_date"] == "2024-01-11"

    def test_no_conn_country_falls_back_to_utc(self, seeded_db):
        # seeded_db has no conn_country — should stay UTC (offset 0)
        patterns = get_listening_patterns(seeded_db)
        assert patterns["peak_hour"] == 12  # T12:00:00Z stays at 12


class TestGetListeningPatternsMostActiveDateDetail:
    def test_most_active_date_play_count(self, seeded_db_tw):
        patterns = get_listening_patterns(seeded_db_tw)
        # Both plays land on 2024-01-11 local TW — play_count = 2
        assert patterns["most_active_date_play_count"] == 2

    def test_most_active_date_total_mins(self, seeded_db_tw):
        patterns = get_listening_patterns(seeded_db_tw)
        # 200_000 + 150_000 = 350_000 ms = 5 min
        assert patterns["most_active_date_total_mins"] == 5

    def test_detail_none_when_db_empty(self, tmp_path):
        db = str(tmp_path / "empty.db")
        init_history_db(db)
        patterns = get_listening_patterns(db)
        assert patterns["most_active_date_play_count"] is None
        assert patterns["most_active_date_total_mins"] is None

    def test_detail_respects_date_filter(self, seeded_db):
        # seeded_db: Jan 10, 11 and Feb 1, 10 — all with 1 play each.
        # Filter to Jan only: most_active_date is one of the Jan dates (1 play).
        # The detail query must not count Feb plays for that date.
        patterns = get_listening_patterns(seeded_db, end_date="2024-01-31")
        assert patterns["most_active_date_play_count"] == 1


class TestHistoryNotInitializedError:
    """Analytics queries should raise HistoryNotInitializedError when the DB
    file is missing or the listening_history table has not been created."""

    def test_subclass_of_history_db_error(self):
        assert issubclass(HistoryNotInitializedError, HistoryDBError)

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
        with pytest.raises(HistoryNotInitializedError):
            get_listening_patterns(db)
        with pytest.raises(HistoryNotInitializedError):
            get_recent_plays(db)

    def test_initialized_empty_db_does_not_raise(self, tmp_path):
        # Empty-but-initialized DB is a valid state — queries should return
        # empty/None results, not raise HistoryNotInitializedError.
        db = str(tmp_path / "empty.db")
        init_history_db(db)
        assert get_top_artists(db) == []
