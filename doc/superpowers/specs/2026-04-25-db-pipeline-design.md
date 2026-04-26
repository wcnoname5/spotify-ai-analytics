# DB Pipeline Design Spec
**Date:** 2026-04-25
**Status:** Approved
**Branch:** spotify-data-pipeline (based on phase1-mcp)

---

## Context

The existing `packages/core/spotify_core/db/` has a working schema and `init_db()` / `get_connection()`, but nothing wires them to data. This spec covers:

- Initializing the history DB from scratch
- Bulk-importing local Spotify JSON exports
- Live-syncing recent plays from the Spotify API
- Inspecting the DB interactively via sqlite3

---

## Decisions

| Question | Decision |
|---|---|
| DB split | `data/tokens.db` (auth only) + `data/history.db` (listening history + sync state) |
| Core logic location | `packages/core/spotify_core/db/pipeline.py` — plain functions, importable by MCP tools |
| CLI scripts | Thin wrappers in `scripts/` that call pipeline functions |
| Inspection | Raw sqlite3 passthrough with printed reference cheatsheet |
| JSON import vs API sync | Two separate commands (`import_json.py`, `sync_api.py`) |
| Dedup key | `SHA1(track_id + ":" + played_at_iso)` stored as `id TEXT PRIMARY KEY` |
| API cursor storage | `sync_state` table, `value INTEGER` (Unix ms timestamp) |

---

## File Layout

```
packages/core/spotify_core/db/
├── schema.py       (update: split tokens/history, add sync_state table)
├── migrations.py   (update: init_history_db() and init_tokens_db() separately)
└── pipeline.py     (NEW: import_json_to_db, sync_api_to_db, open_inspect_shell)

scripts/
├── init_db.py      (create history.db; --auth flag triggers OAuth)
├── import_json.py  (bulk load JSON exports → history.db)
├── sync_api.py     (fetch recent plays from API → history.db)
└── inspect_db.py   (print cheatsheet, exec into sqlite3)
```

---

## Schema Changes

### `data/history.db`

```sql
CREATE TABLE listening_history (
    id          TEXT PRIMARY KEY,   -- SHA1(track_id:played_at_iso)
    track_id    TEXT NOT NULL,
    track_name  TEXT,
    artist_name TEXT,
    album_name  TEXT,
    played_at   DATETIME NOT NULL,
    ms_played   INTEGER,
    source      TEXT DEFAULT 'api'  -- 'json_import' or 'api'
);
CREATE INDEX IF NOT EXISTS idx_played_at ON listening_history (played_at DESC);

CREATE TABLE sync_state (
    key     TEXT PRIMARY KEY,
    value   INTEGER NOT NULL   -- Unix timestamp in milliseconds
);
-- Row: ('last_played_at_ms', <unix_ms>)
```

### `data/tokens.db`

Unchanged — owned exclusively by `spotify_client/token_store.py`.

---

## Data Flow

### JSON Import

```
data/spotify_history/*.json
  → SpotifyDataLoader (existing Polars loader)
  → iterate rows
  → id = SHA1(track_id + ":" + played_at.isoformat())
  → INSERT OR IGNORE INTO listening_history
  → log rows inserted / skipped
```

- Safe to re-run (idempotent via `INSERT OR IGNORE`)
- Uses existing `SpotifyDataLoader` — no re-implementation of JSON parsing

### API Sync

```
sync_state('last_played_at_ms') → after param (omitted on first run)
  → SpotifyClient.get_recently_played(limit=50, after=last_played_at_ms)
  → parse tracks
  → id = SHA1(track_id + ":" + played_at.isoformat())
  → INSERT OR IGNORE INTO listening_history
  → UPDATE sync_state SET value = max(played_at as unix_ms)
```

- Cursor persisted in DB — reruns pick up where they left off
- Safe to re-run (idempotent)
- Spotify returns max 50 tracks per call; run frequently (e.g. every 30 min) to avoid gaps

---

## `pipeline.py` Public API

```python
def init_history_db(db_path: str) -> None:
    """Create history.db and sync_state table. Idempotent."""

def import_json_to_db(json_dir: str, db_path: str) -> dict:
    """Bulk load Streaming*.json files. Returns {'inserted': int, 'skipped': int}."""

def sync_api_to_db(db_path: str, tokens_db_path: str, user_id: str,
                   client_id: str, fernet_key: str) -> dict:
    """Fetch recent plays from Spotify API and upsert. Returns {'inserted': int, 'cursor_ms': int}."""

def open_inspect_shell(db_path: str) -> None:
    """Print SQL cheatsheet, then exec into sqlite3 interactive shell."""
```

All four functions are independently importable — MCP tools can import them directly without going through the scripts.

---

## Scripts

### `scripts/init_db.py`
```bash
uv run python scripts/init_db.py           # create data/history.db
uv run python scripts/init_db.py --auth    # + trigger browser OAuth, store encrypted token
```

### `scripts/import_json.py`
```bash
uv run python scripts/import_json.py --dir data/spotify_history
# Prints: Inserted 1842 rows, skipped 0 duplicates
```

### `scripts/sync_api.py`
```bash
uv run python scripts/sync_api.py --user-id <user_id>
# Prints: Inserted 12 rows, cursor updated to 1745123456789
```

### `scripts/inspect_db.py`
```bash
uv run python scripts/inspect_db.py
# Prints SQL cheatsheet, then drops into: sqlite3 data/history.db
```

All scripts accept `--verbose` to set `logging.DEBUG`.

---

## Inspect Shell

`open_inspect_shell()` prints a reference cheatsheet then calls `subprocess.run(["sqlite3", db_path, "-init", tmp_sqliterc])` with a temp `.sqliterc` that sets `.mode column` and `.headers on`. Uses `subprocess.run` (not `os.execvp`) for Windows compatibility.

Reference queries cover:
- Recent 20 plays
- Top artists by listening time
- Top tracks by play count
- Listening by hour of day
- Row count and date range

---

## Error Handling

| Scenario | Behavior |
|---|---|
| `import_json_to_db()` with empty dir | Warning log, returns `{'inserted': 0, 'skipped': 0}` |
| `sync_api_to_db()` with missing/expired token | `RuntimeError("Run OAuth flow first: uv run python scripts/init_db.py --auth")` |
| Spotify API 429 | Bubbles up from `SpotifyClient` (existing retry logic) |
| `init_history_db()` re-run | No-op — `CREATE TABLE IF NOT EXISTS` |

No `print()` anywhere — all output via `logging` module per CLAUDE.md.

---

## Future MCP Tool Wiring

When `apps/mcp/server.py` is built, tools map directly:

```python
from spotify_core.db.pipeline import sync_api_to_db, import_json_to_db

@mcp.tool()
def sync_history(...):
    return sync_api_to_db(...)

@mcp.tool()
def import_history(...):
    return import_json_to_db(...)
```

No refactoring needed — `pipeline.py` is already the right abstraction layer.

---

## Out of Scope

- Scheduler / cron for recurring sync (run `sync_api.py` manually or via OS scheduler)
- Multi-user support (single `user_id` per local install)
- Backfill beyond the 50-track API limit (Spotify Extended Streaming History export covers this — use `import_json.py`)
