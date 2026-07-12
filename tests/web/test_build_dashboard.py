"""Smoke test for the static dashboard generator (scripts/build_dashboard.py)."""
import datetime
import importlib.util
from pathlib import Path

from spotify_core.db.migrations import get_connection
from spotify_core.db.pipeline import init_history_db

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "build_dashboard", _REPO_ROOT / "scripts" / "build_dashboard.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _seed_db(db_path: str) -> None:
    init_history_db(db_path)
    now = datetime.datetime.now(datetime.timezone.utc)
    conn = get_connection(db_path)
    with conn:
        for i in range(3):
            played_at = (now - datetime.timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M:%SZ")
            conn.execute(
                "INSERT INTO listening_history "
                "(id, track_id, track_name, artist_name, album_name, played_at, ms_played, source) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'api')",
                (f"row{i}", f"spotify:track:track{i}", f"Track {i} <x>", "Test & Artist", "Album", played_at, 180000),
            )
    conn.close()


def test_build_writes_all_period_pages(tmp_path):
    db_path = str(tmp_path / "history.db")
    _seed_db(db_path)
    mod = _load_module()

    written = mod.build(db_path, tmp_path / "site")

    assert [p.name for p in written] == ["last7.html", "index.html", "last90.html", "all.html"]
    index = (tmp_path / "site" / "index.html").read_text(encoding="utf-8")
    assert "Test &amp; Artist" in index          # content present, escaped
    assert "Track 0 &lt;x&gt;" in index
    assert "open.spotify.com/track/track0" in index
    assert "Last updated" in index


def test_build_empty_db_still_publishes(tmp_path):
    db_path = str(tmp_path / "history.db")
    init_history_db(db_path)
    mod = _load_module()

    written = mod.build(db_path, tmp_path / "site")

    assert [p.name for p in written] == ["index.html"]
    assert "No listening history" in written[0].read_text(encoding="utf-8")
