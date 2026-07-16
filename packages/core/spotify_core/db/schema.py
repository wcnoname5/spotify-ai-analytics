"""SQLite schema definitions (DDL, data definition language) for the Spotify AI Analytics database.

listening_history + sync_state + the played_at index are defined in the
shared db/sql/schema.sql (single source of truth, also read by the Tauri
dashboard's TS data layer). spotify_tokens is Python/MCP-only and stays
inline here — it never needs to exist in the Tauri-side cache.
"""
from importlib.resources import files


def _load_ddl_statements() -> list[str]:
    """Read schema.sql and split it into individual CREATE statements.

    Strips `--` line comments before splitting on `;` (the file has no
    semicolons inside comments or string literals), then drops any
    empty/whitespace-only fragments left over from the trailing split.
    """
    raw = files("spotify_core.db.sql").joinpath("schema.sql").read_text()
    lines = []
    for line in raw.splitlines():
        code = line.split("--", 1)[0]
        lines.append(code)
    stripped = "\n".join(lines)
    statements = [s.strip() for s in stripped.split(";")]
    return [s for s in statements if s]


SPOTIFY_TOKENS_DDL = """
CREATE TABLE IF NOT EXISTS spotify_tokens (
    user_id       TEXT PRIMARY KEY,
    access_token  TEXT NOT NULL,
    refresh_token TEXT NOT NULL,
    expires_at    DATETIME NOT NULL,
    scopes        TEXT
);
"""

# DDL for data/history.db (listening history + sync cursor): listening_history,
# sync_state, played_at index — in that order, as they appear in schema.sql.
HISTORY_DDL = _load_ddl_statements()

# HISTORY_DDL plus the Python-only spotify_tokens table, inserted after
# listening_history to match the original ALL_DDL ordering.
ALL_DDL = [HISTORY_DDL[0], SPOTIFY_TOKENS_DDL, *HISTORY_DDL[1:]]
