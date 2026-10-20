import sqlite3

import pytest

from spotify_core.db.schema import all_ddl


@pytest.fixture
def history_db(tmp_path):
    """Factory: a migrated history.db in tmp_path, seeded with `rows`; returns its path.

    Each row needs `id`, `played_at` and `ms_played`; the rest default.
    """
    db = str(tmp_path / "history.db")

    def make(rows=()):
        with sqlite3.connect(db) as conn:
            for ddl in all_ddl():
                conn.execute(ddl)
            conn.executemany(
                "INSERT OR IGNORE INTO listening_history "
                "(id, track_id, track_name, artist_name, played_at, ms_played, source) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        r["id"], r.get("track_id", r["id"]),
                        r.get("track_name", "T"), r.get("artist_name", "A"),
                        r["played_at"], r["ms_played"], r.get("source", "json_import"),
                    )
                    for r in rows
                ],
            )
        return db

    return make
