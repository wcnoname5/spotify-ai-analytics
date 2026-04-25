# DB Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `pipeline.py` (core logic) + four thin scripts (`init_db`, `import_json`, `sync_api`, `inspect_db`) that initialize the history SQLite DB, bulk-import JSON exports, live-sync from the Spotify API, and open an interactive sqlite3 inspection shell.

**Architecture:** All business logic lives in `packages/core/spotify_core/db/pipeline.py` as plain importable functions. Scripts in `scripts/` are thin argument-parsing wrappers. `schema.py` and `migrations.py` gain new history-only DDL and `init_history_db()` alongside the existing `init_db()` (kept for backward compat). MCP tools will import `pipeline.py` directly when `apps/mcp/server.py` is built.

**Tech Stack:** Python stdlib (`sqlite3`, `hashlib`, `subprocess`, `tempfile`, `argparse`), existing `SpotifyDataLoader` (Polars), existing `SpotifyClient` (httpx), existing `get_connection` / `init_db` from `migrations.py`.

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `packages/core/spotify_core/db/schema.py` | Add `SYNC_STATE_DDL`, `HISTORY_DDL` list |
| Modify | `packages/core/spotify_core/db/migrations.py` | Add `init_history_db(db_path)` |
| **Create** | `packages/core/spotify_core/db/pipeline.py` | Core pipeline logic (4 functions) |
| **Create** | `tests/core/test_pipeline.py` | Unit tests for all pipeline functions |
| **Create** | `scripts/init_db.py` | Thin wrapper: init DB + optional OAuth |
| **Create** | `scripts/import_json.py` | Thin wrapper: bulk JSON import |
| **Create** | `scripts/sync_api.py` | Thin wrapper: live API sync |
| **Create** | `scripts/inspect_db.py` | Thin wrapper: open sqlite3 shell |
| Modify | `doc/ARCHITECTURE.md` | Document what was built |

All work is done in the `.worktrees/phase1-mcp/` worktree on branch `spotify-data-pipeline`.

---

## Task 1: Create branch

**Files:** none (git only)

- [ ] **Step 1: Create and switch to new branch inside the worktree**

  Run from the **worktree** directory:
  ```bash
  cd .worktrees/phase1-mcp
  git checkout -b spotify-data-pipeline
  ```
  Expected: `Switched to a new branch 'spotify-data-pipeline'`

- [ ] **Step 2: Verify baseline tests pass before touching anything**

  ```bash
  uv run pytest tests/core/test_db.py -v
  ```
  Expected: all 8 tests PASS (if any fail, stop and investigate before continuing).

---

## Task 2: Extend schema.py with SYNC_STATE_DDL and HISTORY_DDL

**Files:**
- Modify: `packages/core/spotify_core/db/schema.py`

- [ ] **Step 1: Write the failing test**

  Add to `tests/core/test_db.py`:
  ```python
  from spotify_core.db.schema import HISTORY_DDL, SYNC_STATE_DDL

  @pytest.mark.unit
  def test_history_ddl_contains_sync_state(tmp_path):
      """HISTORY_DDL creates sync_state table."""
      db_path = tmp_path / "test.db"
      with sqlite3.connect(db_path) as conn:
          for ddl in HISTORY_DDL:
              conn.execute(ddl)
      with sqlite3.connect(db_path) as conn:
          cols = {row[1] for row in conn.execute("PRAGMA table_info(sync_state)")}
      assert {"key", "value"}.issubset(cols)
  ```

- [ ] **Step 2: Run test to verify it fails**

  ```bash
  uv run pytest tests/core/test_db.py::test_history_ddl_contains_sync_state -v
  ```
  Expected: FAIL with `ImportError: cannot import name 'HISTORY_DDL'`

- [ ] **Step 3: Add SYNC_STATE_DDL and HISTORY_DDL to schema.py**

  Append to `packages/core/spotify_core/db/schema.py` (do not remove anything existing):
  ```python
  SYNC_STATE_DDL = """
  CREATE TABLE IF NOT EXISTS sync_state (
      key    TEXT PRIMARY KEY,
      value  INTEGER NOT NULL
  );
  """

  # DDL for data/history.db (listening history + sync cursor)
  HISTORY_DDL = [LISTENING_HISTORY_DDL, SYNC_STATE_DDL, LISTENING_HISTORY_INDEX_DDL]
  ```

- [ ] **Step 4: Run test to verify it passes**

  ```bash
  uv run pytest tests/core/test_db.py -v
  ```
  Expected: all tests PASS (existing tests still pass, new test passes).

- [ ] **Step 5: Commit**

  ```bash
  git add packages/core/spotify_core/db/schema.py tests/core/test_db.py
  git commit -m "feat(db): add SYNC_STATE_DDL and HISTORY_DDL to schema"
  ```

---

## Task 3: Add init_history_db() to migrations.py

**Files:**
- Modify: `packages/core/spotify_core/db/migrations.py`

- [ ] **Step 1: Write the failing test**

  Add to `tests/core/test_db.py`:
  ```python
  from spotify_core.db.migrations import init_history_db

  @pytest.mark.unit
  def test_init_history_db_creates_tables(tmp_path):
      """init_history_db creates listening_history and sync_state."""
      db_path = tmp_path / "history.db"
      init_history_db(db_path)
      with sqlite3.connect(db_path) as conn:
          tables = {row[0] for row in conn.execute(
              "SELECT name FROM sqlite_master WHERE type='table'"
          )}
      assert "listening_history" in tables
      assert "sync_state" in tables

  @pytest.mark.unit
  def test_init_history_db_idempotent(tmp_path):
      """Calling init_history_db twice does not raise."""
      db_path = tmp_path / "history.db"
      init_history_db(db_path)
      init_history_db(db_path)
  ```

- [ ] **Step 2: Run tests to verify they fail**

  ```bash
  uv run pytest tests/core/test_db.py::test_init_history_db_creates_tables -v
  ```
  Expected: FAIL with `ImportError: cannot import name 'init_history_db'`

- [ ] **Step 3: Add init_history_db() to migrations.py**

  Add after the existing `init_db()` function in `packages/core/spotify_core/db/migrations.py`:
  ```python
  from .schema import ALL_DDL, HISTORY_DDL  # update existing import line

  def init_history_db(db_path: Union[str, Path]) -> None:
      """Create history.db with listening_history, sync_state, and index.

      Does NOT create spotify_tokens — that table lives in tokens.db,
      owned by spotify_client/token_store.py.
      Safe to call multiple times (idempotent).
      """
      db_path = Path(db_path)
      db_path.parent.mkdir(parents=True, exist_ok=True)

      with sqlite3.connect(db_path) as conn:
          conn.execute("PRAGMA journal_mode=WAL")
          conn.execute("PRAGMA foreign_keys=ON")
          for ddl in HISTORY_DDL:
              conn.execute(ddl)
          conn.commit()

      logger.info("History database initialized at %s", db_path)
  ```

  Also update the import line at the top of `migrations.py` from:
  ```python
  from .schema import ALL_DDL
  ```
  to:
  ```python
  from .schema import ALL_DDL, HISTORY_DDL
  ```

- [ ] **Step 4: Run all db tests**

  ```bash
  uv run pytest tests/core/test_db.py -v
  ```
  Expected: all tests PASS.

- [ ] **Step 5: Commit**

  ```bash
  git add packages/core/spotify_core/db/migrations.py tests/core/test_db.py
  git commit -m "feat(db): add init_history_db() for split history/tokens DB"
  ```

---

## Task 4: Create pipeline.py — init_history_db wrapper

**Files:**
- Create: `packages/core/spotify_core/db/pipeline.py`
- Create: `tests/core/test_pipeline.py`

- [ ] **Step 1: Write the failing test**

  Create `tests/core/test_pipeline.py`:
  ```python
  """Tests for spotify_core.db.pipeline."""
  import sqlite3
  import json
  import pytest
  from pathlib import Path
  from unittest.mock import patch, MagicMock
  from spotify_core.db.pipeline import init_history_db, import_json_to_db, sync_api_to_db


  @pytest.mark.unit
  def test_pipeline_init_creates_history_db(tmp_path):
      """init_history_db creates listening_history and sync_state tables."""
      db = tmp_path / "history.db"
      init_history_db(str(db))
      with sqlite3.connect(db) as conn:
          tables = {r[0] for r in conn.execute(
              "SELECT name FROM sqlite_master WHERE type='table'"
          )}
      assert "listening_history" in tables
      assert "sync_state" in tables


  @pytest.mark.unit
  def test_pipeline_init_idempotent(tmp_path):
      """Calling init_history_db twice does not raise."""
      db = tmp_path / "history.db"
      init_history_db(str(db))
      init_history_db(str(db))
  ```

- [ ] **Step 2: Run tests to verify they fail**

  ```bash
  uv run pytest tests/core/test_pipeline.py -v
  ```
  Expected: FAIL with `ModuleNotFoundError: No module named 'spotify_core.db.pipeline'`

- [ ] **Step 3: Create pipeline.py with init_history_db**

  Create `packages/core/spotify_core/db/pipeline.py`:
  ```python
  """Data pipeline: initialize, import, sync, and inspect the history DB."""
  import hashlib
  import logging
  import sqlite3
  import subprocess
  import tempfile
  from datetime import datetime, timezone
  from pathlib import Path
  from typing import Optional

  from spotify_dataloader.data_loader import SpotifyDataLoader
  from .migrations import init_history_db as _migrations_init_history_db, get_connection
  from ..spotify_client.client import SpotifyClient
  from ..spotify_client.token_store import load_tokens, is_token_expired

  logger = logging.getLogger(__name__)

  _CHEATSHEET = """
  === Spotify History DB — Quick Reference ===
  DB: {db_path}

  -- Recent 20 plays
  SELECT played_at, track_name, artist_name, ms_played/1000 AS secs
  FROM listening_history ORDER BY played_at DESC LIMIT 20;

  -- Top artists by total listening time (minutes)
  SELECT artist_name, SUM(ms_played)/60000 AS minutes
  FROM listening_history GROUP BY artist_name ORDER BY minutes DESC LIMIT 10;

  -- Top tracks by play count
  SELECT track_name, artist_name, COUNT(*) AS plays
  FROM listening_history GROUP BY track_id ORDER BY plays DESC LIMIT 10;

  -- Listening by hour of day
  SELECT strftime('%H', played_at) AS hour, COUNT(*) AS plays
  FROM listening_history GROUP BY hour ORDER BY hour;

  -- Row count and date range
  SELECT COUNT(*) AS total, MIN(played_at) AS earliest, MAX(played_at) AS latest
  FROM listening_history;

  -- Sync cursor (last API sync timestamp in ms)
  SELECT key, value FROM sync_state;
  ============================================
  """


  def init_history_db(db_path: str) -> None:
      """Create data/history.db with listening_history and sync_state tables.

      Idempotent — safe to call multiple times.
      """
      _migrations_init_history_db(db_path)


  def import_json_to_db(json_dir: str, db_path: str) -> dict:
      """Bulk load Streaming*.json files into listening_history.

      Returns:
          {"inserted": int, "skipped": int}
      """
      ...  # implemented in Task 5


  def sync_api_to_db(
      db_path: str,
      tokens_db_path: str,
      user_id: str,
      client_id: str,
      fernet_key: bytes,
  ) -> dict:
      """Fetch the 50 most recent plays from the Spotify API and upsert.

      Returns:
          {"inserted": int, "cursor_ms": int}
      """
      ...  # implemented in Task 6


  def open_inspect_shell(db_path: str) -> None:
      """Print SQL cheatsheet then launch sqlite3 interactive shell."""
      ...  # implemented in Task 7
  ```

- [ ] **Step 4: Run tests to verify they pass**

  ```bash
  uv run pytest tests/core/test_pipeline.py::test_pipeline_init_creates_history_db tests/core/test_pipeline.py::test_pipeline_init_idempotent -v
  ```
  Expected: both PASS.

- [ ] **Step 5: Commit**

  ```bash
  git add packages/core/spotify_core/db/pipeline.py tests/core/test_pipeline.py
  git commit -m "feat(db): scaffold pipeline.py with init_history_db"
  ```

---

## Task 5: Implement import_json_to_db()

**Files:**
- Modify: `packages/core/spotify_core/db/pipeline.py`
- Modify: `tests/core/test_pipeline.py`

- [ ] **Step 1: Write the failing tests**

  Add to `tests/core/test_pipeline.py`:
  ```python
  @pytest.fixture
  def sample_json_dir(tmp_path):
      """Create a temp dir with one Streaming_test.json matching sample format."""
      records = [
          {
              "ts": "2024-01-15T08:30:00Z",
              "platform": "Windows",
              "conn_country": "US",
              "master_metadata_track_name": "Bohemian Rhapsody",
              "master_metadata_album_artist_name": "Queen",
              "master_metadata_album_album_name": "A Night at the Opera",
              "ms_played": 354000,
              "spotify_track_uri": "spotify:track:001",
              "reason_start": "trackdone",
              "reason_end": "trackdone",
              "shuffle": False,
              "skipped": False,
          },
          {
              "ts": "2024-01-15T09:00:00Z",
              "platform": "iOS",
              "conn_country": "US",
              "master_metadata_track_name": "Stairway to Heaven",
              "master_metadata_album_artist_name": "Led Zeppelin",
              "master_metadata_album_album_name": "Led Zeppelin IV",
              "ms_played": 482000,
              "spotify_track_uri": "spotify:track:002",
              "reason_start": "trackdone",
              "reason_end": "trackdone",
              "shuffle": False,
              "skipped": False,
          },
      ]
      f = tmp_path / "Streaming_test.json"
      f.write_text(json.dumps(records))
      return tmp_path


  @pytest.fixture
  def history_db(tmp_path):
      """Initialized history DB."""
      db = tmp_path / "history.db"
      init_history_db(str(db))
      return db


  @pytest.mark.unit
  def test_import_json_inserts_rows(sample_json_dir, history_db):
      """import_json_to_db inserts rows from JSON files."""
      result = import_json_to_db(str(sample_json_dir), str(history_db))
      assert result["inserted"] == 2
      assert result["skipped"] == 0
      with sqlite3.connect(history_db) as conn:
          count = conn.execute("SELECT COUNT(*) FROM listening_history").fetchone()[0]
      assert count == 2


  @pytest.mark.unit
  def test_import_json_idempotent(sample_json_dir, history_db):
      """Importing the same files twice skips duplicates."""
      import_json_to_db(str(sample_json_dir), str(history_db))
      result = import_json_to_db(str(sample_json_dir), str(history_db))
      assert result["inserted"] == 0
      assert result["skipped"] == 2


  @pytest.mark.unit
  def test_import_json_empty_dir(tmp_path, history_db):
      """import_json_to_db with empty dir returns zeros without raising."""
      result = import_json_to_db(str(tmp_path), str(history_db))
      assert result == {"inserted": 0, "skipped": 0}


  @pytest.mark.unit
  def test_import_json_source_field(sample_json_dir, history_db):
      """Imported rows have source='json_import'."""
      import_json_to_db(str(sample_json_dir), str(history_db))
      with sqlite3.connect(history_db) as conn:
          sources = {r[0] for r in conn.execute("SELECT DISTINCT source FROM listening_history")}
      assert sources == {"json_import"}
  ```

- [ ] **Step 2: Run tests to verify they fail**

  ```bash
  uv run pytest tests/core/test_pipeline.py::test_import_json_inserts_rows -v
  ```
  Expected: FAIL (function body is `...`)

- [ ] **Step 3: Implement import_json_to_db()**

  Replace the `...` stub in `pipeline.py`:
  ```python
  def import_json_to_db(json_dir: str, db_path: str) -> dict:
      """Bulk load Streaming*.json files into listening_history.

      Returns:
          {"inserted": int, "skipped": int}
      """
      json_path = Path(json_dir)
      if not list(json_path.rglob("Streaming*.json")):
          logger.warning("No Streaming*.json files found in %s", json_dir)
          return {"inserted": 0, "skipped": 0}

      loader = SpotifyDataLoader(directory=json_path)
      df = loader.df
      if df is None or df.is_empty():
          return {"inserted": 0, "skipped": 0}

      inserted = skipped = 0
      conn = get_connection(db_path)
      try:
          for row in df.iter_rows(named=True):
              track_uri = row.get("track_uri") or ""
              ts_str = row.get("ts") or ""
              try:
                  played_dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                  played_at_iso = played_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
              except (ValueError, AttributeError):
                  logger.warning("Skipping row with unparseable ts: %s", ts_str)
                  skipped += 1
                  continue

              row_id = hashlib.sha1(f"{track_uri}:{played_at_iso}".encode()).hexdigest()

              ms_played_val = row.get("ms_played")
              ms_played_int = (
                  int(ms_played_val.total_seconds() * 1000)
                  if ms_played_val is not None
                  else None
              )

              cur = conn.execute(
                  "INSERT OR IGNORE INTO listening_history "
                  "(id, track_id, track_name, artist_name, album_name, "
                  " played_at, ms_played, source) "
                  "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                  (
                      row_id, track_uri,
                      row.get("track"), row.get("artist"), row.get("album"),
                      played_at_iso, ms_played_int, "json_import",
                  ),
              )
              if cur.rowcount > 0:
                  inserted += 1
              else:
                  skipped += 1
          conn.commit()
      finally:
          conn.close()

      logger.info("JSON import: %d inserted, %d skipped", inserted, skipped)
      return {"inserted": inserted, "skipped": skipped}
  ```

- [ ] **Step 4: Run tests to verify they pass**

  ```bash
  uv run pytest tests/core/test_pipeline.py -k "import_json" -v
  ```
  Expected: all 4 import_json tests PASS.

- [ ] **Step 5: Commit**

  ```bash
  git add packages/core/spotify_core/db/pipeline.py tests/core/test_pipeline.py
  git commit -m "feat(db): implement import_json_to_db() in pipeline"
  ```

---

## Task 6: Implement sync_api_to_db()

**Files:**
- Modify: `packages/core/spotify_core/db/pipeline.py`
- Modify: `tests/core/test_pipeline.py`

- [ ] **Step 1: Write the failing tests**

  Add to `tests/core/test_pipeline.py`:
  ```python
  def _make_recently_played_response(items):
      """Build a mock Spotify recently-played API response."""
      return {"items": items}


  def _make_track_item(track_uri, track_name, artist_name, album_name, played_at, duration_ms=180000):
      return {
          "track": {
              "uri": track_uri,
              "name": track_name,
              "artists": [{"name": artist_name}],
              "album": {"name": album_name},
              "duration_ms": duration_ms,
          },
          "played_at": played_at,
      }


  @pytest.mark.unit
  def test_sync_api_inserts_rows(history_db, tmp_path):
      """sync_api_to_db inserts rows returned by the API."""
      tokens_db = tmp_path / "tokens.db"
      fake_key = b"fake_key"
      items = [
          _make_track_item(
              "spotify:track:AAA", "Song A", "Artist A", "Album A",
              "2024-02-01T10:00:00.000Z"
          ),
          _make_track_item(
              "spotify:track:BBB", "Song B", "Artist B", "Album B",
              "2024-02-01T10:05:00.000Z"
          ),
      ]
      mock_response = _make_recently_played_response(items)

      with patch("spotify_core.db.pipeline.is_token_expired", return_value=False), \
           patch("spotify_core.db.pipeline.load_tokens", return_value={"access_token": "tok"}), \
           patch("spotify_core.db.pipeline.SpotifyClient") as MockClient:
          mock_instance = MagicMock()
          mock_instance.get_recently_played.return_value = mock_response
          MockClient.return_value.__enter__ = MagicMock(return_value=mock_instance)
          MockClient.return_value.__exit__ = MagicMock(return_value=False)

          result = sync_api_to_db(
              str(history_db), str(tokens_db), "user1", "client_id", fake_key
          )

      assert result["inserted"] == 2
      with sqlite3.connect(history_db) as conn:
          count = conn.execute("SELECT COUNT(*) FROM listening_history").fetchone()[0]
      assert count == 2


  @pytest.mark.unit
  def test_sync_api_updates_cursor(history_db, tmp_path):
      """sync_api_to_db writes the newest played_at as cursor in sync_state."""
      tokens_db = tmp_path / "tokens.db"
      fake_key = b"fake_key"
      items = [
          _make_track_item(
              "spotify:track:CCC", "Song C", "Artist C", "Album C",
              "2024-02-01T10:00:00.000Z"
          ),
      ]

      with patch("spotify_core.db.pipeline.is_token_expired", return_value=False), \
           patch("spotify_core.db.pipeline.load_tokens", return_value={"access_token": "tok"}), \
           patch("spotify_core.db.pipeline.SpotifyClient") as MockClient:
          mock_instance = MagicMock()
          mock_instance.get_recently_played.return_value = _make_recently_played_response(items)
          MockClient.return_value.__enter__ = MagicMock(return_value=mock_instance)
          MockClient.return_value.__exit__ = MagicMock(return_value=False)

          result = sync_api_to_db(
              str(history_db), str(tokens_db), "user1", "client_id", fake_key
          )

      assert result["cursor_ms"] > 0
      with sqlite3.connect(history_db) as conn:
          row = conn.execute(
              "SELECT value FROM sync_state WHERE key='last_played_at_ms'"
          ).fetchone()
      assert row is not None
      assert row[0] == result["cursor_ms"]


  @pytest.mark.unit
  def test_sync_api_idempotent(history_db, tmp_path):
      """sync_api_to_db with same items twice inserts 0 on second call."""
      tokens_db = tmp_path / "tokens.db"
      fake_key = b"fake_key"
      items = [
          _make_track_item(
              "spotify:track:DDD", "Song D", "Artist D", "Album D",
              "2024-02-01T11:00:00.000Z"
          ),
      ]

      def run_sync():
          with patch("spotify_core.db.pipeline.is_token_expired", return_value=False), \
               patch("spotify_core.db.pipeline.load_tokens", return_value={"access_token": "tok"}), \
               patch("spotify_core.db.pipeline.SpotifyClient") as MockClient:
              mock_instance = MagicMock()
              mock_instance.get_recently_played.return_value = _make_recently_played_response(items)
              MockClient.return_value.__enter__ = MagicMock(return_value=mock_instance)
              MockClient.return_value.__exit__ = MagicMock(return_value=False)
              return sync_api_to_db(
                  str(history_db), str(tokens_db), "user1", "client_id", fake_key
              )

      first = run_sync()
      second = run_sync()
      assert first["inserted"] == 1
      assert second["inserted"] == 0
      assert second["cursor_ms"] == first["cursor_ms"]


  @pytest.mark.unit
  def test_sync_api_no_token_raises(history_db, tmp_path):
      """sync_api_to_db raises RuntimeError when no token exists."""
      tokens_db = tmp_path / "tokens.db"
      with patch("spotify_core.db.pipeline.is_token_expired", return_value=True), \
           patch("spotify_core.db.pipeline.load_tokens", return_value=None):
          with pytest.raises(RuntimeError, match="Run OAuth flow first"):
              sync_api_to_db(str(history_db), str(tokens_db), "user1", "client_id", b"key")
  ```

- [ ] **Step 2: Run tests to verify they fail**

  ```bash
  uv run pytest tests/core/test_pipeline.py::test_sync_api_inserts_rows -v
  ```
  Expected: FAIL (function body is `...`)

- [ ] **Step 3: Implement sync_api_to_db()**

  Replace the `...` stub in `pipeline.py`:
  ```python
  def sync_api_to_db(
      db_path: str,
      tokens_db_path: str,
      user_id: str,
      client_id: str,
      fernet_key: bytes,
  ) -> dict:
      """Fetch the 50 most recent plays from the Spotify API and upsert.

      Returns:
          {"inserted": int, "cursor_ms": int}
      """
      # Guard: token must exist and be loadable
      if is_token_expired(tokens_db_path, user_id):
          token_data = load_tokens(tokens_db_path, user_id, fernet_key)
          if token_data is None:
              raise RuntimeError(
                  "Run OAuth flow first: uv run python scripts/init_db.py --auth"
              )

      # Read current cursor
      conn = get_connection(db_path)
      try:
          row = conn.execute(
              "SELECT value FROM sync_state WHERE key='last_played_at_ms'"
          ).fetchone()
          last_cursor_ms: Optional[int] = row["value"] if row else None
      finally:
          conn.close()

      # Fetch from Spotify
      with SpotifyClient(tokens_db_path, user_id, client_id, fernet_key) as client:
          response = client.get_recently_played(limit=50, after=last_cursor_ms)

      items = response.get("items", [])
      if not items:
          logger.info("No new tracks from Spotify API")
          return {"inserted": 0, "cursor_ms": last_cursor_ms or 0}

      inserted = skipped = 0
      new_cursor_ms = last_cursor_ms or 0

      conn = get_connection(db_path)
      try:
          for item in items:
              track = item.get("track", {})
              track_uri = track.get("uri", "")
              played_at_str = item.get("played_at", "")

              try:
                  played_dt = datetime.fromisoformat(played_at_str.replace("Z", "+00:00"))
                  played_at_iso = played_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
                  played_at_ms = int(played_dt.timestamp() * 1000)
              except (ValueError, AttributeError):
                  logger.warning("Skipping item with unparseable played_at: %s", played_at_str)
                  skipped += 1
                  continue

              row_id = hashlib.sha1(f"{track_uri}:{played_at_iso}".encode()).hexdigest()
              artists = track.get("artists") or []
              artist_name = artists[0]["name"] if artists else None
              album_name = (track.get("album") or {}).get("name")
              # recently-played API gives duration_ms (full track length), not actual play time
              ms_played = track.get("duration_ms")

              cur = conn.execute(
                  "INSERT OR IGNORE INTO listening_history "
                  "(id, track_id, track_name, artist_name, album_name, "
                  " played_at, ms_played, source) "
                  "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                  (
                      row_id, track_uri, track.get("name"),
                      artist_name, album_name,
                      played_at_iso, ms_played, "api",
                  ),
              )
              if cur.rowcount > 0:
                  inserted += 1
                  new_cursor_ms = max(new_cursor_ms, played_at_ms)
              else:
                  skipped += 1

          if new_cursor_ms > (last_cursor_ms or 0):
              conn.execute(
                  "INSERT OR REPLACE INTO sync_state (key, value) "
                  "VALUES ('last_played_at_ms', ?)",
                  (new_cursor_ms,),
              )
          conn.commit()
      finally:
          conn.close()

      logger.info("API sync: %d inserted, %d skipped, cursor=%d", inserted, skipped, new_cursor_ms)
      return {"inserted": inserted, "cursor_ms": new_cursor_ms}
  ```

- [ ] **Step 4: Run tests to verify they pass**

  ```bash
  uv run pytest tests/core/test_pipeline.py -k "sync_api" -v
  ```
  Expected: all 4 sync_api tests PASS.

- [ ] **Step 5: Commit**

  ```bash
  git add packages/core/spotify_core/db/pipeline.py tests/core/test_pipeline.py
  git commit -m "feat(db): implement sync_api_to_db() in pipeline"
  ```

---

## Task 7: Implement open_inspect_shell()

**Files:**
- Modify: `packages/core/spotify_core/db/pipeline.py`
- Modify: `tests/core/test_pipeline.py`

- [ ] **Step 1: Write the failing test**

  Add to `tests/core/test_pipeline.py`:
  ```python
  from spotify_core.db.pipeline import open_inspect_shell

  @pytest.mark.unit
  def test_open_inspect_shell_prints_cheatsheet(history_db, capsys):
      """open_inspect_shell prints the cheatsheet before launching sqlite3."""
      with patch("spotify_core.db.pipeline.subprocess.run") as mock_run:
          mock_run.return_value = MagicMock(returncode=0)
          open_inspect_shell(str(history_db))
      captured = capsys.readouterr()
      assert "listening_history" in captured.out
      assert "Top artists" in captured.out


  @pytest.mark.unit
  def test_open_inspect_shell_calls_sqlite3(history_db):
      """open_inspect_shell invokes sqlite3 with the correct db path."""
      with patch("spotify_core.db.pipeline.subprocess.run") as mock_run:
          mock_run.return_value = MagicMock(returncode=0)
          open_inspect_shell(str(history_db))
      call_args = mock_run.call_args[0][0]
      assert call_args[0] == "sqlite3"
      assert str(history_db) in call_args
  ```

- [ ] **Step 2: Run tests to verify they fail**

  ```bash
  uv run pytest tests/core/test_pipeline.py::test_open_inspect_shell_prints_cheatsheet -v
  ```
  Expected: FAIL (function body is `...`)

- [ ] **Step 3: Implement open_inspect_shell()**

  Replace the `...` stub in `pipeline.py`:
  ```python
  def open_inspect_shell(db_path: str) -> None:
      """Print SQL cheatsheet then launch sqlite3 interactive shell."""
      print(_CHEATSHEET.format(db_path=db_path))

      sqliterc = ".mode column\n.headers on\n"
      with tempfile.NamedTemporaryFile(
          mode="w", suffix=".sqliterc", delete=False
      ) as f:
          f.write(sqliterc)
          tmp_rc = f.name

      try:
          subprocess.run(["sqlite3", db_path, "-init", tmp_rc], check=False)
      finally:
          Path(tmp_rc).unlink(missing_ok=True)
  ```

- [ ] **Step 4: Run all pipeline tests**

  ```bash
  uv run pytest tests/core/test_pipeline.py -v
  ```
  Expected: all tests PASS.

- [ ] **Step 5: Run the full test suite to confirm no regressions**

  ```bash
  uv run pytest -v
  ```
  Expected: all tests PASS (no regressions in test_db.py or other modules).

- [ ] **Step 6: Commit**

  ```bash
  git add packages/core/spotify_core/db/pipeline.py tests/core/test_pipeline.py
  git commit -m "feat(db): implement open_inspect_shell() in pipeline"
  ```

---

## Task 8: Write thin script wrappers

**Files:**
- Create: `scripts/init_db.py`
- Create: `scripts/import_json.py`
- Create: `scripts/sync_api.py`
- Create: `scripts/inspect_db.py`

No TDD for thin wrappers — they are argument-parsing shells only.
Run each manually to verify they import and print help without errors.

- [ ] **Step 1: Create scripts/init_db.py**

  ```python
  """Initialize data/history.db and optionally trigger OAuth flow."""
  import argparse
  import logging
  import os
  import sys
  from pathlib import Path

  sys.path.insert(0, str(Path(__file__).parent.parent))

  from spotify_core.db.pipeline import init_history_db
  from spotify_core.logging import setup_logging

  logger = logging.getLogger(__name__)


  def main():
      parser = argparse.ArgumentParser(description="Initialize the Spotify history database")
      parser.add_argument(
          "--db", default="data/history.db",
          help="Path to history.db (default: data/history.db)"
      )
      parser.add_argument(
          "--auth", action="store_true",
          help="After DB init, run the Spotify OAuth PKCE flow to store tokens"
      )
      parser.add_argument(
          "--tokens-db", default="data/tokens.db",
          help="Path to tokens.db (default: data/tokens.db, used with --auth)"
      )
      parser.add_argument("--verbose", action="store_true")
      args = parser.parse_args()

      setup_logging(level=logging.DEBUG if args.verbose else logging.INFO)

      logger.info("Initializing history DB at %s", args.db)
      init_history_db(args.db)
      logger.info("Done. DB ready at %s", args.db)

      if args.auth:
          from spotify_core.spotify_client.auth import run_pkce_flow
          from spotify_core.spotify_client.token_store import save_tokens
          from cryptography.fernet import Fernet

          client_id = os.environ.get("SPOTIFY_CLIENT_ID")
          fernet_key_str = os.environ.get("TOKEN_ENCRYPT_KEY")
          if not client_id:
              logger.error("SPOTIFY_CLIENT_ID not set in environment")
              sys.exit(1)
          if not fernet_key_str:
              logger.error("TOKEN_ENCRYPT_KEY not set — generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"")
              sys.exit(1)

          fernet_key = fernet_key_str.encode()
          logger.info("Starting OAuth PKCE flow — your browser will open")
          token_data = run_pkce_flow(client_id=client_id)
          user_id = token_data.get("user_id", "default")
          save_tokens(args.tokens_db, user_id, token_data, fernet_key)
          logger.info("Tokens saved for user_id='%s' in %s", user_id, args.tokens_db)


  if __name__ == "__main__":
      main()
  ```

- [ ] **Step 2: Create scripts/import_json.py**

  ```python
  """Bulk-import Spotify JSON history exports into history.db."""
  import argparse
  import logging
  import sys
  from pathlib import Path

  sys.path.insert(0, str(Path(__file__).parent.parent))

  from spotify_core.db.pipeline import import_json_to_db
  from spotify_core.logging import setup_logging

  logger = logging.getLogger(__name__)


  def main():
      parser = argparse.ArgumentParser(
          description="Bulk-import Streaming*.json files into history.db"
      )
      parser.add_argument(
          "--dir", default="data/spotify_history",
          help="Directory containing Streaming*.json files (default: data/spotify_history)"
      )
      parser.add_argument(
          "--db", default="data/history.db",
          help="Path to history.db (default: data/history.db)"
      )
      parser.add_argument("--verbose", action="store_true")
      args = parser.parse_args()

      setup_logging(level=logging.DEBUG if args.verbose else logging.INFO)

      logger.info("Importing JSON from %s into %s", args.dir, args.db)
      result = import_json_to_db(args.dir, args.db)
      logger.info("Inserted %d rows, skipped %d duplicates", result["inserted"], result["skipped"])


  if __name__ == "__main__":
      main()
  ```

- [ ] **Step 3: Create scripts/sync_api.py**

  ```python
  """Sync recent Spotify plays from the API into history.db."""
  import argparse
  import logging
  import os
  import sys
  from pathlib import Path

  sys.path.insert(0, str(Path(__file__).parent.parent))

  from spotify_core.db.pipeline import sync_api_to_db
  from spotify_core.logging import setup_logging

  logger = logging.getLogger(__name__)


  def main():
      parser = argparse.ArgumentParser(
          description="Fetch recent plays from Spotify API and upsert into history.db"
      )
      parser.add_argument(
          "--user-id", required=True,
          help="Spotify user ID (same value used during --auth)"
      )
      parser.add_argument(
          "--db", default="data/history.db",
          help="Path to history.db (default: data/history.db)"
      )
      parser.add_argument(
          "--tokens-db", default="data/tokens.db",
          help="Path to tokens.db (default: data/tokens.db)"
      )
      parser.add_argument("--verbose", action="store_true")
      args = parser.parse_args()

      setup_logging(level=logging.DEBUG if args.verbose else logging.INFO)

      client_id = os.environ.get("SPOTIFY_CLIENT_ID")
      fernet_key_str = os.environ.get("TOKEN_ENCRYPT_KEY")
      if not client_id:
          logger.error("SPOTIFY_CLIENT_ID not set in environment")
          sys.exit(1)
      if not fernet_key_str:
          logger.error("TOKEN_ENCRYPT_KEY not set in environment")
          sys.exit(1)

      logger.info("Syncing recent plays for user '%s'", args.user_id)
      result = sync_api_to_db(
          db_path=args.db,
          tokens_db_path=args.tokens_db,
          user_id=args.user_id,
          client_id=client_id,
          fernet_key=fernet_key_str.encode(),
      )
      logger.info(
          "Inserted %d rows, cursor updated to %d ms",
          result["inserted"], result["cursor_ms"]
      )


  if __name__ == "__main__":
      main()
  ```

- [ ] **Step 4: Create scripts/inspect_db.py**

  ```python
  """Open an interactive sqlite3 shell for history.db with a SQL cheatsheet."""
  import argparse
  import sys
  from pathlib import Path

  sys.path.insert(0, str(Path(__file__).parent.parent))

  from spotify_core.db.pipeline import open_inspect_shell


  def main():
      parser = argparse.ArgumentParser(
          description="Inspect history.db interactively via sqlite3"
      )
      parser.add_argument(
          "--db", default="data/history.db",
          help="Path to history.db (default: data/history.db)"
      )
      args = parser.parse_args()
      open_inspect_shell(args.db)


  if __name__ == "__main__":
      main()
  ```

- [ ] **Step 5: Verify scripts import cleanly**

  ```bash
  uv run python scripts/init_db.py --help
  uv run python scripts/import_json.py --help
  uv run python scripts/sync_api.py --help
  uv run python scripts/inspect_db.py --help
  ```
  Expected: each prints usage without error.

- [ ] **Step 6: Run full test suite one final time**

  ```bash
  uv run pytest -v
  ```
  Expected: all tests PASS.

- [ ] **Step 7: Commit**

  ```bash
  git add scripts/
  git commit -m "feat(scripts): add init_db, import_json, sync_api, inspect_db thin wrappers"
  ```

---

## Task 9: Update ARCHITECTURE.md

**Files:**
- Modify: `doc/ARCHITECTURE.md`

- [ ] **Step 1: Add a section documenting what was built**

  Append to `doc/ARCHITECTURE.md` after Section 4 (Core Package Specs):

  ```markdown
  ### 4.5 `packages/core/db/pipeline.py` (BUILT — Phase 1)

  Four plain Python functions, independently importable by MCP tools:

  | Function | Purpose |
  |---|---|
  | `init_history_db(db_path)` | Create `data/history.db` with `listening_history` + `sync_state` tables |
  | `import_json_to_db(json_dir, db_path)` | Bulk load `Streaming*.json` exports; returns `{inserted, skipped}` |
  | `sync_api_to_db(db_path, tokens_db_path, user_id, client_id, fernet_key)` | Fetch 50 most recent plays from API, upsert; returns `{inserted, cursor_ms}` |
  | `open_inspect_shell(db_path)` | Print SQL cheatsheet, launch `sqlite3` interactive shell |

  Dedup key: `SHA1(track_uri + ":" + played_at_iso)` stored as `id TEXT PRIMARY KEY`.
  Cursor: `sync_state` table row `('last_played_at_ms', <unix_ms_int>)` persists API sync position.
  Tokens DB (`data/tokens.db`) is untouched — owned by `spotify_client/token_store.py`.

  ### DB Quick-Start (human user)

  ```bash
  # 1. Initialize DB
  uv run python scripts/init_db.py

  # 2. Trigger OAuth (first time only — opens browser)
  uv run python scripts/init_db.py --auth

  # 3. Bulk-import local JSON export
  uv run python scripts/import_json.py --dir data/spotify_history

  # 4. Sync latest plays from Spotify
  uv run python scripts/sync_api.py --user-id <your_spotify_user_id>

  # 5. Inspect interactively
  uv run python scripts/inspect_db.py
  ```
  ```

- [ ] **Step 2: Commit**

  ```bash
  git add doc/ARCHITECTURE.md
  git commit -m "docs: document pipeline.py and DB quick-start in ARCHITECTURE.md"
  ```

---

## Done

All four pipeline functions implemented and tested. Full test suite passing. Scripts verified. Architecture documented.

Next step when ready: wire `import_json_to_db` and `sync_api_to_db` as MCP tools in `apps/mcp/server.py`.
