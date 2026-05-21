"""Tests for MCP utility helpers and DB query helpers."""
import sqlite3
import pytest
from datetime import datetime
from spotify_core.db.errors import HistoryNotInitializedError
from spotify_core.db.queries import is_history_empty
from spotify_core.spotify_client.errors import (
    SpotifyAuthError,
    SpotifyNoActiveDeviceError,
    SpotifyPremiumRequiredError,
)
from spotify_mcp.utils import to_error_response, utc_iso_to_local


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


class TestToErrorResponse:
    def test_auth_error_adds_requires_auth(self):
        result = to_error_response(SpotifyAuthError("No token found"), "bob")
        assert result["requires_auth"] is True
        assert result["auth_command"] == "spotify-mcp reauth"
        assert "No token found" in result["error"]

    def test_premium_error_returns_canonical_message(self):
        result = to_error_response(SpotifyPremiumRequiredError("HTTP 403: ..."), "bob")
        assert result == {"error": "Spotify Premium required for playback control."}

    def test_no_active_device_without_list_devices(self):
        result = to_error_response(SpotifyNoActiveDeviceError("HTTP 404: ..."), "bob")
        assert "No active Spotify device" in result["error"]
        assert result["available_devices"] == []
        assert "hint" in result

    def test_no_active_device_with_list_devices(self):
        devices = [{"id": "dev1", "name": "Phone"}]
        result = to_error_response(
            SpotifyNoActiveDeviceError("HTTP 404: ..."),
            "bob",
            list_devices=lambda: devices,
        )
        assert result["available_devices"] == devices

    def test_no_active_device_swallows_list_devices_error(self):
        def bad_list():
            raise RuntimeError("network")

        result = to_error_response(
            SpotifyNoActiveDeviceError("HTTP 404: ..."), "bob", list_devices=bad_list
        )
        assert result["available_devices"] == []

    def test_unknown_exception_falls_through(self):
        result = to_error_response(RuntimeError("Network timeout"), "bob")
        assert result == {"error": "Network timeout"}
        assert "requires_auth" not in result

    def test_history_not_initialized_adds_requires_import(self):
        result = to_error_response(
            HistoryNotInitializedError("listening_history table missing"), "bob"
        )
        assert result["requires_import"] is True
        assert "import_hint" in result
        assert "listening_history" in result["error"]
        # Must not be confused with an auth failure.
        assert "requires_auth" not in result
