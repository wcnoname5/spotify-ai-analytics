"""SQLite schema definitions for the Spotify AI Analytics database."""

LISTENING_HISTORY_DDL = """
CREATE TABLE IF NOT EXISTS listening_history (
    id           TEXT PRIMARY KEY,
    track_id     TEXT NOT NULL,
    track_name   TEXT,
    artist_name  TEXT,
    album_name   TEXT,
    played_at    DATETIME NOT NULL, -- stored in ISO format (UTC)
    ms_played    INTEGER,
    source       TEXT DEFAULT 'api' CHECK(source IN ('api', 'json_import')),
    platform     TEXT,
    conn_country TEXT,
    reason_start TEXT,
    reason_end   TEXT,
    shuffle      INTEGER,            -- BOOLEAN stored as 0/1
    skipped      INTEGER             -- BOOLEAN stored as 0/1
);
"""

SPOTIFY_TOKENS_DDL = """
CREATE TABLE IF NOT EXISTS spotify_tokens (
    user_id       TEXT PRIMARY KEY,
    access_token  TEXT NOT NULL,
    refresh_token TEXT NOT NULL,
    expires_at    DATETIME NOT NULL,
    scopes        TEXT
);
"""

# Index for common queries
LISTENING_HISTORY_INDEX_DDL = """
CREATE INDEX IF NOT EXISTS idx_listening_history_played_at
    ON listening_history(played_at DESC);
"""

SYNC_STATE_DDL = """
CREATE TABLE IF NOT EXISTS sync_state (
    key    TEXT PRIMARY KEY,
    value  INTEGER NOT NULL
);
"""

# DDL for data/history.db (listening history + sync cursor)
HISTORY_DDL = [LISTENING_HISTORY_DDL, SYNC_STATE_DDL, LISTENING_HISTORY_INDEX_DDL]

ALL_DDL = [LISTENING_HISTORY_DDL, SPOTIFY_TOKENS_DDL, SYNC_STATE_DDL, LISTENING_HISTORY_INDEX_DDL]
