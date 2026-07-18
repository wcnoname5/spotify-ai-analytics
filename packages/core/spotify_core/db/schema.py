"""SQLite DDL. History tables come from the shared db/sql/schema.sql;
spotify_tokens is Python/MCP-only and stays inline here."""
from importlib.resources import files


def _load_ddl_statements() -> list[str]:
    """Split schema.sql into CREATE statements; strip `--` comments first (they contain `;`)."""
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

HISTORY_DDL = _load_ddl_statements()

# HISTORY_DDL plus the Python-only spotify_tokens table, inserted after
# listening_history to match the original ALL_DDL ordering.
ALL_DDL = [HISTORY_DDL[0], SPOTIFY_TOKENS_DDL, *HISTORY_DDL[1:]]
