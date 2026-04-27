"""Tests for MCP utility helpers and DB query helpers."""
import sqlite3
import pytest
from datetime import datetime
from spotify_core.db.queries import is_history_empty
from spotify_mcp.utils import utc_iso_to_local, enrich_auth_error


class TestIsHistoryEmpty:
    def test_missing_file_returns_true(self):
        assert is_history_empty("/nonexistent/path/to/history.db") is True

    def test_db_with_no_table_returns_true(self, tmp_path):
        db = str(tmp_path / "test.db")
        sqlite3.connect(db).close()  # create empty file, no tables
        assert is_history_empty(db) is True

    def test_empty_table_returns_true(self, tmp_path):
        db = str(tmp_path / "test.db")
        with sqlite3.connect(db) as conn:
            conn.execute("CREATE TABLE listening_history (id TEXT PRIMARY KEY)")
        assert is_history_empty(db) is True

    def test_rows_present_returns_false(self, tmp_path):
        db = str(tmp_path / "test.db")
        with sqlite3.connect(db) as conn:
            conn.execute("CREATE TABLE listening_history (id TEXT PRIMARY KEY)")
            conn.execute("INSERT INTO listening_history VALUES ('abc')")
        assert is_history_empty(db) is False


class TestUtcIsoToLocal:
    def test_none_returns_none(self):
        assert utc_iso_to_local(None) is None

    def test_malformed_string_returned_unchanged(self):
        assert utc_iso_to_local("not-a-date") == "not-a-date"

    def test_valid_utc_returns_parseable_iso(self):
        result = utc_iso_to_local("2024-06-15T12:00:00Z")
        assert result is not None
        dt = datetime.fromisoformat(result)
        assert dt.year == 2024
        assert dt.month == 6
        assert dt.day == 15

    def test_already_offset_aware_string_works(self):
        result = utc_iso_to_local("2024-06-15T12:00:00+00:00")
        assert result is not None
        dt = datetime.fromisoformat(result)
        assert dt.year == 2024


class TestEnrichAuthError:
    def test_no_token_found_adds_requires_auth(self):
        result = enrich_auth_error({"error": "No token found for user 'bob'"}, "bob")
        assert result["requires_auth"] is True

    def test_no_stored_token_adds_requires_auth(self):
        result = enrich_auth_error({"error": "No stored token for user 'bob'"}, "bob")
        assert result["requires_auth"] is True

    def test_cannot_refresh_adds_requires_auth(self):
        result = enrich_auth_error({"error": "Cannot refresh — no stored token"}, "bob")
        assert result["requires_auth"] is True

    def test_auth_command_contains_user_id(self):
        result = enrich_auth_error({"error": "No token found for user 'alice'"}, "alice")
        assert "alice" in result["auth_command"]

    def test_non_auth_error_unchanged(self):
        result = enrich_auth_error({"error": "Network timeout"}, "bob")
        assert "requires_auth" not in result
        assert result == {"error": "Network timeout"}

    def test_success_dict_unchanged(self):
        result = enrich_auth_error({"status": "paused"}, "bob")
        assert result == {"status": "paused"}
