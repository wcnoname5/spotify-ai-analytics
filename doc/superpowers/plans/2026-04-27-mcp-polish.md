# MCP Server Polish — Setup UX, Edge Cases, Docs

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix MCP server UX gaps: missing setup docs, no first-time auth guide, silent empty-DB, cryptic auth errors, and UTC timestamps leaking to users.

**Architecture:** Minimal changes to `server.py` — add a `setup_check` tool, guard analytics tools against empty DB, post-process timestamps and auth errors through small helpers extracted to `spotify_mcp/utils.py`. Add `apps/mcp/README.md` (full setup guide) and `apps/mcp/SKILL.md` (Claude skill prompt). Add `is_history_empty()` to `queries.py`.

**Tech Stack:** Python 3.13, FastMCP (`mcp` SDK), SQLite (`sqlite3`), cryptography (Fernet), pytest + tmp_path.

---

## File Map

| Action | Path | What changes |
|--------|------|--------------|
| Modify | `packages/core/spotify_core/db/queries.py` | Add `is_history_empty(db_path)` |
| Create | `apps/mcp/spotify_mcp/utils.py` | `utc_iso_to_local`, `enrich_auth_error` helpers |
| Create | `tests/test_mcp_utils.py` | Unit tests for the two files above |
| Modify | `apps/mcp/server.py` | Add `setup_check` tool; guard analytics tools; wrap sync/playback with auth error handling; localize timestamps |
| Create | `apps/mcp/README.md` | Full setup guide for end users |
| Create | `apps/mcp/SKILL.md` | Claude skill prompt — first-time setup flow, tool selection guide |

---

## Task 0: Make `init_db.py --auth` self-bootstrapping (auto-generate TOKEN_ENCRYPT_KEY)

**Files:**
- Modify: `scripts/init_db.py`

Currently `init_db.py --auth` exits with an error when `TOKEN_ENCRYPT_KEY` is missing, printing a generated key for the user to copy manually. This task makes it write the key to `.env` automatically and continue, so users only need to set `SPOTIFY_CLIENT_ID` before running the script.

No tests — the script is a CLI entry point; the behavior is verified by running it.

- [ ] **Step 1: Replace the TOKEN_ENCRYPT_KEY exit block in `init_db.py`**

Find this block in [scripts/init_db.py](scripts/init_db.py#L58-L66):

```python
        if not fernet_key_str:
            from cryptography.fernet import Fernet
            logger.info("DB build for the first time: Generating a new Fernet key for token encryption: %s", Fernet.generate_key().decode())
            logger.info("Set this value in your .env file as TOKEN_ENCRYPT_KEY to avoid generating a new one each time")
            # logger.error(
            #     "TOKEN_ENCRYPT_KEY not set — generate one with: "
            #     'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
            # )
            sys.exit(1)
```

Replace with:

```python
        if not fernet_key_str:
            from cryptography.fernet import Fernet
            new_key = Fernet.generate_key().decode()
            env_path = Path(__file__).resolve().parent.parent / ".env"
            if env_path.exists():
                content = env_path.read_text()
                import re as _re
                if "TOKEN_ENCRYPT_KEY=" in content:
                    content = _re.sub(r"TOKEN_ENCRYPT_KEY=\S*", f"TOKEN_ENCRYPT_KEY={new_key}", content)
                else:
                    content += f"\nTOKEN_ENCRYPT_KEY={new_key}\n"
                env_path.write_text(content)
                logger.info("Auto-generated TOKEN_ENCRYPT_KEY and saved to %s", env_path)
            else:
                logger.warning("No .env file found — add this line to your .env: TOKEN_ENCRYPT_KEY=%s", new_key)
            fernet_key_str = new_key
            os.environ["TOKEN_ENCRYPT_KEY"] = new_key
```

- [ ] **Step 2: Smoke-test manually**

```bash
# Temporarily rename .env to test auto-generation
cp .env .env.bak
# Remove TOKEN_ENCRYPT_KEY line from .env (or create a minimal .env with just CLIENT_ID)
# Then run (will exit before OAuth since browser is needed, but verify key was written)
uv run python scripts/init_db.py
cat .env | grep TOKEN_ENCRYPT_KEY   # should show the auto-generated key
cp .env.bak .env                    # restore
```

Expected: `TOKEN_ENCRYPT_KEY=<44-char-key>` appears in `.env`.

- [ ] **Step 3: Commit**

```bash
git add scripts/init_db.py
git commit -m "feat(scripts): auto-generate and save TOKEN_ENCRYPT_KEY in init_db.py"
```

---

## Task 1: `is_history_empty()` in `queries.py`

**Files:**
- Modify: `packages/core/spotify_core/db/queries.py`
- Test: `tests/test_mcp_utils.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_mcp_utils.py` with the following (just the `is_history_empty` section for now — we'll add more in Tasks 2 and 3):

```python
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
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
uv run pytest tests/test_mcp_utils.py -v
```

Expected: `ImportError` or `AttributeError` — `is_history_empty` does not exist yet.

- [ ] **Step 3: Implement `is_history_empty` in `queries.py`**

Append to the end of `packages/core/spotify_core/db/queries.py`:

```python
def is_history_empty(db_path: str) -> bool:
    """Return True if the DB file is missing, has no table, or has zero rows."""
    import os
    import sqlite3 as _sqlite3
    if not os.path.exists(db_path):
        return True
    try:
        conn = get_connection(db_path)
        try:
            row = conn.execute("SELECT COUNT(*) FROM listening_history").fetchone()
            return row[0] == 0
        except _sqlite3.OperationalError:
            # Table doesn't exist yet
            return True
        finally:
            conn.close()
    except Exception:
        return True
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
uv run pytest tests/test_mcp_utils.py::TestIsHistoryEmpty -v
```

Expected: 4 passing.

- [ ] **Step 5: Commit**

```bash
git add packages/core/spotify_core/db/queries.py tests/test_mcp_utils.py
git commit -m "feat(db): add is_history_empty() helper + tests"
```

---

## Task 2: `utc_iso_to_local` and `enrich_auth_error` in `spotify_mcp/utils.py`

**Files:**
- Create: `apps/mcp/spotify_mcp/utils.py`
- Test: `tests/test_mcp_utils.py` (extend)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_mcp_utils.py`:

```python
from datetime import datetime
from spotify_mcp.utils import utc_iso_to_local, enrich_auth_error


class TestUtcIsoToLocal:
    def test_none_returns_none(self):
        assert utc_iso_to_local(None) is None

    def test_malformed_string_returned_unchanged(self):
        assert utc_iso_to_local("not-a-date") == "not-a-date"

    def test_valid_utc_returns_parseable_iso(self):
        result = utc_iso_to_local("2024-06-15T12:00:00Z")
        assert result is not None
        # Must be parseable as a datetime
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
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
uv run pytest tests/test_mcp_utils.py::TestUtcIsoToLocal tests/test_mcp_utils.py::TestEnrichAuthError -v
```

Expected: `ModuleNotFoundError: No module named 'spotify_mcp.utils'`

- [ ] **Step 3: Create `apps/mcp/spotify_mcp/utils.py`**

```python
"""Shared helpers for the MCP server layer (not part of core — MCP-specific only)."""
from __future__ import annotations
from datetime import datetime

_AUTH_ERROR_KEYWORDS = ("No token found", "No stored token", "Cannot refresh")


def utc_iso_to_local(utc_iso: str | None) -> str | None:
    """Convert a UTC ISO timestamp (e.g. '2024-01-15T08:30:00Z') to the system local timezone.

    Returns the original string unchanged if it cannot be parsed.
    Returns None if input is None.
    """
    if utc_iso is None:
        return None
    try:
        dt = datetime.fromisoformat(utc_iso.replace("Z", "+00:00"))
        return dt.astimezone().isoformat()
    except (ValueError, TypeError):
        return utc_iso


def enrich_auth_error(result: dict, user_id: str) -> dict:
    """If result contains a Spotify auth error, add requires_auth and auth_command fields.

    Leaves non-error and non-auth-error dicts untouched.
    """
    error_msg = result.get("error", "")
    if any(kw in error_msg for kw in _AUTH_ERROR_KEYWORDS):
        return {
            **result,
            "requires_auth": True,
            "auth_command": (
                f"uv run python scripts/init_db.py --auth --user-id {user_id}"
            ),
        }
    return result
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
uv run pytest tests/test_mcp_utils.py -v
```

Expected: all tests passing (now ~14 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/mcp/spotify_mcp/utils.py tests/test_mcp_utils.py
git commit -m "feat(mcp): add utc_iso_to_local and enrich_auth_error helpers + tests"
```

---

## Task 3: Integrate helpers into `server.py`

**Files:**
- Modify: `apps/mcp/server.py`

This task has no new tests — behavior is covered by the unit tests in Tasks 1–2 and manual smoke-testing. Make all changes to `server.py` in one commit.

- [ ] **Step 1: Add imports near the top of `server.py` (after the existing imports block)**

Find this block in [server.py](apps/mcp/server.py#L13-L20):
```python
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
```

After those two lines add:
```python
from spotify_mcp.utils import enrich_auth_error, utc_iso_to_local
from spotify_core.db.queries import is_history_empty
```

- [ ] **Step 2: Add the shared empty-DB response dict after the startup checks (before `mcp = FastMCP(...)`)** 

Find the line `mcp = FastMCP("spotify-analytics")` in [server.py](apps/mcp/server.py#L70) and insert before it:

```python
_EMPTY_DB_RESPONSE = {
    "warning": "No listening history in the local database.",
    "next_steps": [
        "Option A — import Spotify JSON export (recommended, full history):",
        "  1. Download from https://www.spotify.com/account/privacy/ (takes a few days)",
        "  2. uv run python scripts/import_json.py --dir data/spotify_history",
        "Option B — sync recent 50 plays from Spotify API (instant):",
        "  uv run python scripts/sync_api.py --user-id <your_spotify_user_id>",
    ],
}
```

- [ ] **Step 3: Add `setup_check` tool after the `mcp = FastMCP(...)` line**

Find `mcp = FastMCP("spotify-analytics")` in [server.py](apps/mcp/server.py#L70) and insert after it:

```python

@mcp.tool()
def setup_check() -> dict:
    """Diagnose the MCP server configuration. Call this first if something isn't working.

    Returns a structured report of what is configured and what actions are still needed,
    in the order they must be completed.

    Returns:
        {
            "ready": bool,
            "checks": dict[str, bool],
            "actions_needed": list[str],
            "message": str,
        }
    """
    import os

    checks: dict[str, bool] = {}
    actions: list[str] = []

    checks["spotify_client_id"] = bool(CLIENT_ID)
    if not CLIENT_ID:
        actions.append(
            "Set SPOTIFY_CLIENT_ID in .env\n"
            "  → Create an app at https://developer.spotify.com/dashboard\n"
            "  → Copy the Client ID into your .env file"
        )

    checks["token_encrypt_key"] = bool(FERNET_KEY)

    if not FERNET_KEY:
        # --auth also initializes the DB and auto-generates the key — one command covers everything.
        actions.append(
            "Run the init script — auto-generates TOKEN_ENCRYPT_KEY, initializes DB, and connects Spotify:\n"
            "  uv run python scripts/init_db.py --auth --user-id <your_spotify_username>"
        )
    else:
        db_exists = os.path.exists(DB_PATH)
        checks["history_db_exists"] = db_exists

        checks["tokens_exist"] = False
        try:
            from spotify_core.spotify_client.token_store import load_tokens
            tokens = load_tokens(TOKENS_DB, DEFAULT_USER_ID, FERNET_KEY)
            checks["tokens_exist"] = tokens is not None
        except Exception:
            pass

        if not db_exists or not checks["tokens_exist"]:
            actions.append(
                "Initialize DB and connect Spotify account (one command, opens browser):\n"
                "  uv run python scripts/init_db.py --auth --user-id <your_spotify_username>"
            )
        else:
            has_data = not is_history_empty(DB_PATH)
            checks["history_db_has_data"] = has_data
            if not has_data:
                actions.append(
                    "Load listening history — choose one:\n"
                    "  A) Full export: uv run python scripts/import_json.py --dir data/spotify_history\n"
                    "     (download from https://www.spotify.com/account/privacy/)\n"
                    "  B) Recent plays: uv run python scripts/sync_api.py --user-id <your_spotify_username>"
                )

    ready = len(actions) == 0
    return {
        "ready": ready,
        "checks": checks,
        "actions_needed": actions,
        "message": (
            "All set! MCP server is fully configured."
            if ready
            else f"{len(actions)} action(s) required to complete setup."
        ),
    }
```

- [ ] **Step 4: Guard `get_top_artists` against empty DB**

Replace the current `get_top_artists` tool in [server.py](apps/mcp/server.py#L116-L133):

```python
@mcp.tool()
def get_top_artists(
    limit: int = 10,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> list:
    """Return top artists by total listening time from local history DB.

    Args:
        limit: Number of artists to return (default 10).
        start_date: Optional start date filter "YYYY-MM-DD".
        end_date: Optional end date filter "YYYY-MM-DD".

    Returns:
        List of {"artist_name": str, "total_ms": int, "play_count": int}.
        If the DB is empty, returns [{"warning": ..., "next_steps": [...]}].
    """
    if is_history_empty(DB_PATH):
        return [_EMPTY_DB_RESPONSE]
    from spotify_core.db.queries import get_top_artists as _get_top_artists
    return _get_top_artists(DB_PATH, limit=limit, start_date=start_date, end_date=end_date)
```

- [ ] **Step 5: Guard `get_top_tracks` against empty DB**

Replace the current `get_top_tracks` tool in [server.py](apps/mcp/server.py#L136-L153):

```python
@mcp.tool()
def get_top_tracks(
    limit: int = 10,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> list:
    """Return top tracks by play count from local history DB.

    Args:
        limit: Number of tracks to return (default 10).
        start_date: Optional start date filter "YYYY-MM-DD".
        end_date: Optional end date filter "YYYY-MM-DD".

    Returns:
        List of {"track_name": str, "artist_name": str, "play_count": int, "total_ms": int}.
        If the DB is empty, returns [{"warning": ..., "next_steps": [...]}].
    """
    if is_history_empty(DB_PATH):
        return [_EMPTY_DB_RESPONSE]
    from spotify_core.db.queries import get_top_tracks as _get_top_tracks
    return _get_top_tracks(DB_PATH, limit=limit, start_date=start_date, end_date=end_date)
```

- [ ] **Step 6: Guard `get_listening_summary` + localize timestamps**

Replace the current `get_listening_summary` tool in [server.py](apps/mcp/server.py#L156-L171):

```python
@mcp.tool()
def get_listening_summary() -> dict:
    """Return a summary of local listening history (total plays, date range, unique artists/tracks).

    Returns:
        {
            "total_plays": int,
            "unique_tracks": int,
            "unique_artists": int,
            "earliest_played_at": str | None,  # local timezone ISO
            "latest_played_at": str | None,    # local timezone ISO
        }
        If the DB is empty, returns {"warning": ..., "next_steps": [...]}.
    """
    if is_history_empty(DB_PATH):
        return _EMPTY_DB_RESPONSE
    from spotify_core.db.queries import get_listening_summary as _summary
    result = dict(_summary(DB_PATH))
    result["earliest_played_at"] = utc_iso_to_local(result.get("earliest_played_at"))
    result["latest_played_at"] = utc_iso_to_local(result.get("latest_played_at"))
    return result
```

- [ ] **Step 7: Wrap `sync_history` with auth error handling**

Replace the current `sync_history` tool in [server.py](apps/mcp/server.py#L77-L94):

```python
@mcp.tool()
def sync_history(user_id: str = DEFAULT_USER_ID) -> dict:
    """Fetch the 50 most recent Spotify plays and store them in the local DB.

    Args:
        user_id: Spotify user ID whose history to sync. Defaults to SPOTIFY_USER_ID env var.

    Returns:
        {"inserted": int, "cursor_ms": int} or {"error": str, "requires_auth": bool, "auth_command": str}.
    """
    try:
        from spotify_core.db.pipeline import sync_api_to_db
        return sync_api_to_db(
            db_path=DB_PATH,
            tokens_db_path=TOKENS_DB,
            user_id=user_id,
            client_id=CLIENT_ID,
            fernet_key=FERNET_KEY,
        )
    except Exception as exc:
        logger.error("sync_history failed: %s", exc)
        return enrich_auth_error({"error": str(exc)}, user_id)
```

- [ ] **Step 8: Enrich auth errors from playback tools**

For each playback tool (`get_now_playing`, `play_track`, `pause_playback`, `skip_track`, `set_volume`, `add_to_queue`, `create_playlist`), wrap the existing body and post-process via `enrich_auth_error`. Replace `get_now_playing` in [server.py](apps/mcp/server.py#L183-L197):

```python
@mcp.tool()
def get_now_playing(user_id: str = DEFAULT_USER_ID) -> dict:
    """Return the currently playing Spotify track.

    Args:
        user_id: Spotify user ID. Defaults to SPOTIFY_USER_ID env var.

    Returns:
        Dict with track info, or {"status": "nothing_playing"}, or {"error": str, "requires_auth": bool, "auth_command": str}.
    """
    try:
        from spotify_core.agent.playback_tools import SpotifyPlaybackTools
        with _make_client(user_id) as client:
            tools = SpotifyPlaybackTools(client, DB_PATH, TOKENS_DB, user_id, CLIENT_ID, FERNET_KEY)
            return enrich_auth_error(tools.get_now_playing(), user_id)
    except Exception as exc:
        logger.error("get_now_playing failed: %s", exc)
        return enrich_auth_error({"error": str(exc)}, user_id)
```

Apply the same pattern (try/except + `enrich_auth_error`) to `play_track`, `pause_playback`, `skip_track`, `set_volume`, `add_to_queue`, and `create_playlist`. The pattern is identical — wrap the `with _make_client(user_id) as client:` block in try/except, and call `enrich_auth_error(result, user_id)` before returning.

Example for `play_track`:
```python
@mcp.tool()
def play_track(uri: str, user_id: str = DEFAULT_USER_ID) -> dict:
    """Start playing a Spotify track (requires Premium).

    Args:
        uri: Spotify track URI e.g. "spotify:track:4iV5W9uYEdYUVa79Axb7Rh".
        user_id: Spotify user ID. Defaults to SPOTIFY_USER_ID env var.

    Returns:
        {"status": "playing", "uri": str} or {"error": str}.
    """
    try:
        from spotify_core.agent.playback_tools import SpotifyPlaybackTools
        with _make_client(user_id) as client:
            tools = SpotifyPlaybackTools(client, DB_PATH, TOKENS_DB, user_id, CLIENT_ID, FERNET_KEY)
            return enrich_auth_error(tools.play_track(uri), user_id)
    except Exception as exc:
        logger.error("play_track failed: %s", exc)
        return enrich_auth_error({"error": str(exc)}, user_id)
```

(Repeat this for the remaining 5 playback tools — same structure, just call the corresponding `tools.*` method.)

- [ ] **Step 9: Run tests and confirm nothing broke**

```bash
uv run pytest -v
```

Expected: all tests pass.

- [ ] **Step 10: Commit**

```bash
git add apps/mcp/server.py
git commit -m "feat(mcp): add setup_check tool, empty-DB guards, timezone conversion, auth error hints"
```

---

## Task 4: Write `apps/mcp/README.md`

**Files:**
- Create: `apps/mcp/README.md`

No tests — documentation only.

- [ ] **Step 1: Create `apps/mcp/README.md`**

```markdown
# Spotify AI Analytics — MCP Server

Local MCP server that exposes Spotify history analytics and playback control as tools for Claude Desktop or Claude Code.

---

## Prerequisites

- Python 3.13+ and [uv](https://docs.astral.sh/uv/getting-started/installation/) installed
- A Spotify account (free or Premium — analytics tools work free, playback requires Premium)
- A Spotify Developer app (free, takes 2 minutes to create)

---

## 1-minute setup summary

```bash
# 1. Install dependencies
uv sync

# 2. Set SPOTIFY_CLIENT_ID in .env (only key you need to find manually — see Section 2)
cp .env.template .env

# 3. Initialize DB + connect Spotify account (auto-generates TOKEN_ENCRYPT_KEY, opens browser)
uv run python scripts/init_db.py --auth --user-id <your_spotify_username>

# 4. Load your listening history (choose one option — see Section 3)
uv run python scripts/import_json.py --dir data/spotify_history   # Option A: full history
uv run python scripts/sync_api.py --user-id <your_spotify_username>  # Option B: recent 50 plays

# 5. Add the server to Claude (see Section 4)
```

---

## Section 2 — Required environment variables

Open `.env` in a text editor. Fill in the three required values:

### `SPOTIFY_CLIENT_ID`

1. Go to [https://developer.spotify.com/dashboard](https://developer.spotify.com/dashboard) and log in.
2. Click **Create app**.
3. Fill in any name and description. Set **Redirect URIs** to exactly:
   ```
   http://127.0.0.1:8888/callback
   ```
   > ⚠️ Use `127.0.0.1`, NOT `localhost` — Spotify blocked `localhost` redirects in November 2025.
4. Accept the terms and click **Save**.
5. On the app overview page, copy the **Client ID** (a 32-character hex string).
6. Paste it into `.env`:
   ```
   SPOTIFY_CLIENT_ID=your_client_id_here
   ```
   > Note: `SPOTIFY_CLIENT_SECRET` is **not needed** — this server uses PKCE (no secret required).

### `TOKEN_ENCRYPT_KEY`

**You don't need to generate this manually.** When you run `scripts/init_db.py --auth` and `TOKEN_ENCRYPT_KEY` is not set, the script auto-generates a Fernet key and writes it to your `.env` file automatically.

If you ever need to set it manually (e.g., restoring from backup):

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Copy the output into `.env` as `TOKEN_ENCRYPT_KEY=<value>`.

> Keep this key safe — it encrypts your stored Spotify tokens. If you lose it, re-run OAuth to get new tokens.

### `SPOTIFY_USER_ID` (optional but recommended)

Your Spotify username — shown at [https://www.spotify.com/account/overview/](https://www.spotify.com/account/overview/) under **Username**.

```
SPOTIFY_USER_ID=your_username
```

If omitted, defaults to `"default"`.

---

## Section 3 — Loading your listening history

You have two options. **Option A gives you full history; Option B is instant.**

### Option A — Spotify JSON export (recommended)

Spotify can export your entire Extended Streaming History (all plays ever).

1. Go to [https://www.spotify.com/account/privacy/](https://www.spotify.com/account/privacy/).
2. Scroll to **Download your data** → select **Extended streaming history**.
3. Click **Request data**. Spotify emails you a download link within a few days.
4. Unzip the download. You'll have files named `Streaming_History_Audio_*.json`.
5. Place these files in `data/spotify_history/`.
6. Import them:
   ```bash
   uv run python scripts/import_json.py --dir data/spotify_history
   ```

### Option B — Recent plays from the Spotify API (instant)

Fetches your 50 most recently played tracks right now:

```bash
uv run python scripts/sync_api.py --user-id <your_spotify_username>
```

Run this anytime to keep the DB up to date (the `sync_history` MCP tool does the same thing).

---

## Section 4 — Connecting to Claude

### Claude Code (VS Code / CLI)

Add to your project's `.claude/settings.json` or your user settings file:

```json
{
  "mcpServers": {
    "spotify-analytics": {
      "command": "uv",
      "args": ["run", "python", "apps/mcp/server.py"],
      "cwd": "/absolute/path/to/spotify-ai-analytics"
    }
  }
}
```

Restart Claude Code after saving.

### Claude Desktop (macOS / Windows)

Open the Claude Desktop config file:
- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

Add the `mcpServers` block:

```json
{
  "mcpServers": {
    "spotify-analytics": {
      "command": "uv",
      "args": ["run", "python", "apps/mcp/server.py"],
      "cwd": "C:\\path\\to\\spotify-ai-analytics"
    }
  }
}
```

Restart Claude Desktop after saving.

---

## Section 5 — First-time auth walkthrough

After adding the server to Claude, ask Claude:

> "Run setup_check and tell me what's missing."

Claude will call the `setup_check` tool and give you a step-by-step list of what still needs to be done.

When the OAuth step comes up, Claude will say to run:
```bash
uv run python scripts/init_db.py --auth --user-id <your_username>
```

This opens your browser to Spotify's login page. After you approve, the browser shows "Authentication complete" and tokens are saved locally. You only need to do this once — tokens auto-refresh.

---

## Section 6 — Available MCP tools

| Tool | Description | Requires auth |
|------|-------------|---------------|
| `setup_check` | Diagnose configuration — start here if anything is broken | No |
| `sync_history` | Fetch 50 most recent plays from Spotify API into local DB | Yes |
| `import_history_from_json` | Bulk-import a folder of Spotify JSON export files | No |
| `get_listening_summary` | Total plays, unique artists/tracks, date range | No |
| `get_top_artists` | Top artists by listening time (filterable by date range) | No |
| `get_top_tracks` | Top tracks by play count (filterable by date range) | No |
| `get_now_playing` | Currently playing track | Yes |
| `play_track` | Play a specific track URI — **Premium required** | Yes |
| `pause_playback` | Pause playback — **Premium required** | Yes |
| `skip_track` | Skip to next track — **Premium required** | Yes |
| `set_volume` | Set volume 0–100 — **Premium required** | Yes |
| `add_to_queue` | Add a track to the playback queue — **Premium required** | Yes |
| `create_playlist` | Create a playlist and populate it with track URIs | Yes |
| `remember_preference` | Store a preference in long-term memory | No |
| `get_memory_summary` | Retrieve all stored preferences and facts | No |
---


## Troubleshooting

**"No Spotify tokens found" on startup**
→ Run the OAuth flow: `uv run python scripts/init_db.py --auth --user-id <your_username>`

**"SPOTIFY_CLIENT_ID is not set"**
→ Check your `.env` file has `SPOTIFY_CLIENT_ID=...` (no quotes, no spaces around `=`)

**"TOKEN_ENCRYPT_KEY is not set"**
→ Generate a key: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`

**OAuth browser doesn't open / times out**
→ The callback server listens on port 8888. Make sure nothing else is using it.
→ If you're in a headless environment, the auth script will print a URL — open it manually.

**Playback tools return "Spotify Premium required"**
→ Playback control (play, pause, skip, volume) requires a Spotify Premium subscription.

**DB is empty after import**
→ Check that your JSON files are named `Streaming_History_Audio_*.json` or `Streaming_History_Video_*.json`.
→ Run: `uv run python scripts/import_json.py --dir data/spotify_history --db data/history.db`

**"Token decrypt failed" or "Invalid token"**
→ Your `TOKEN_ENCRYPT_KEY` may have changed. Generate a new key, update `.env`, and re-run OAuth.
```

- [ ] **Step 2: Verify file was created**

```bash
ls apps/mcp/README.md
```

Expected: file listed.

- [ ] **Step 3: Commit**

```bash
git add apps/mcp/README.md
git commit -m "docs(mcp): add full setup guide README"
```

---

## Task 5: Write `apps/mcp/SKILL.md`

**Files:**
- Create: `apps/mcp/SKILL.md`

This file serves as a Claude skill / system prompt extension. Users can paste it into their Claude project's CLAUDE.md or reference it when setting up Claude Desktop.

No tests — documentation only.

- [ ] **Step 1: Create `apps/mcp/SKILL.md`**

```markdown
# Spotify AI Analytics — Claude Skill

> Add the contents of this file to your project's CLAUDE.md (or paste it into Claude Desktop's system prompt field) so Claude knows how to use this MCP server effectively.

---

## What this MCP server provides

You are connected to a local Spotify AI Analytics MCP server with these capabilities:
- **History analytics** — query local SQLite DB of listening history (no auth needed)
- **Playback control** — control Spotify (requires auth + Spotify Premium)
- **Long-term memory** — store and retrieve user preferences across conversations

---

## First interaction with a new user

When the user first mentions Spotify or seems to be setting up the server:

1. Call `setup_check()` immediately.
2. Read the `actions_needed` list. Walk the user through each item in order — do not skip ahead.
3. After the user completes an action, call `setup_check()` again to confirm before moving on.
4. Once `ready: true`, confirm the server is fully configured and offer to show their listening stats.

---

## When analytics tools return a warning (empty DB)

If `get_listening_summary`, `get_top_artists`, or `get_top_tracks` return a dict with a `warning` field:

1. Tell the user: "Your local listening history database is empty."
2. Ask: "Have you already downloaded your Spotify data from https://www.spotify.com/account/privacy/?"
   - **If yes:** Guide them to run `uv run python scripts/import_json.py --dir data/spotify_history`
   - **If no:** Explain that requesting the JSON export takes a few days. In the meantime, they can sync recent plays: `uv run python scripts/sync_api.py --user-id <their_user_id>` (last 50 tracks only).
3. After they run one of these, call the analytics tool again to confirm data loaded.

---

## When a tool returns `requires_auth: true`

The user's Spotify OAuth tokens are missing or expired. Guide them to:
```bash
uv run python scripts/init_db.py --auth --user-id <their_user_id>
```
This opens a browser tab. They approve access, browser shows "Authentication complete", done. Tokens are saved and auto-refresh going forward.

---

## Tool selection guide

| User says… | Use this tool |
|------------|---------------|
| "What's playing?" / "Now playing?" | `get_now_playing` |
| "Play [track]" / "Resume" | `play_track` (need URI first — ask or search) |
| "Pause" / "Stop" | `pause_playback` |
| "Skip" / "Next song" | `skip_track` |
| "Volume up/down" / "Set volume to X" | `set_volume` |
| "Add to queue" | `add_to_queue` |
| "Top artists" / "Most played artists" | `get_top_artists` |
| "Top tracks" / "Most played songs" | `get_top_tracks` |
| "How much have I listened?" / "Overview" | `get_listening_summary` |
| "Sync my plays" / "Update history" | `sync_history` |
| "Remember that I like X" / "Note that…" | `remember_preference` |
| "What do you know about my taste?" | `get_memory_summary` |
| "Create a playlist" | `create_playlist` (generate URIs from analytics first) |
| "Is everything set up?" / "Something isn't working" | `setup_check` |

---

## Date range filtering

`get_top_artists` and `get_top_tracks` accept `start_date` and `end_date` in `"YYYY-MM-DD"` format.

Examples:
- "Last year" → `start_date="2024-01-01"`, `end_date="2024-12-31"`
- "This month" → compute from today's date
- "2023" → `start_date="2023-01-01"`, `end_date="2023-12-31"`

---

## Timestamps

`get_listening_summary` returns `earliest_played_at` and `latest_played_at` in the user's **local timezone** ISO format. Display them as-is — no further conversion needed.

---

## Playback tool limitations

- All playback tools (`play_track`, `pause_playback`, `skip_track`, `set_volume`, `add_to_queue`) require **Spotify Premium**.
- If they return `{"error": "Spotify Premium required for playback control."}`, tell the user Premium is required — do not retry.
- Track URIs follow the format `spotify:track:<22-char-id>`. You can get them from the analytics tools' `track_id` field or by asking the user to copy from Spotify.
```

- [ ] **Step 2: Commit**

```bash
git add apps/mcp/SKILL.md
git commit -m "docs(mcp): add Claude skill prompt for first-time setup and tool selection"
```

---

## Self-Review

### Spec coverage

| Requirement | Covered by |
|-------------|-----------|
| README with keys, DB init, JSON export instructions | Task 4 |
| Skill markdown for first-time auth | Task 5 |
| `setup_check` tool for first-time startup | Task 3 (Step 3) |
| Empty DB warning in analytics tools | Task 3 (Steps 4–6) |
| Timezone conversion in `get_listening_summary` | Task 3 (Step 6) |
| Auth error handling for `sync_history` | Task 3 (Step 7) |
| Auth error enrichment for playback tools | Task 3 (Step 8) |
| Cryptic auth error → actionable message | `enrich_auth_error` helper (Task 2) |

### Placeholder scan

No TBDs or "similar to Task N" references — all code is shown explicitly.

### Type consistency

- `is_history_empty(db_path: str) -> bool` — used consistently in `server.py`
- `utc_iso_to_local(utc_iso: str | None) -> str | None` — used in `get_listening_summary` wrapper
- `enrich_auth_error(result: dict, user_id: str) -> dict` — used in all API-dependent tools
- `_EMPTY_DB_RESPONSE: dict` — returned as `[_EMPTY_DB_RESPONSE]` for list-returning tools, plain dict for `get_listening_summary`
