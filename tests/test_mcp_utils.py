"""Tests for MCP utility helpers and DB query helpers."""
import sqlite3
import pytest
from spotify_core.db.queries import is_history_empty


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
