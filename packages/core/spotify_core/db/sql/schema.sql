CREATE TABLE IF NOT EXISTS listening_history (
    id           TEXT PRIMARY KEY,
    track_id     TEXT NOT NULL,
    track_name   TEXT,
    artist_name  TEXT,
    album_name   TEXT,
    played_at    DATETIME NOT NULL, -- stored in ISO format (UTC)
    ms_played    INTEGER,
    source       TEXT DEFAULT 'api' CHECK(source IN ('api', 'json_import')),
    platform     TEXT,              -- export-only column (streaming history JSON)
    conn_country TEXT,              -- export-only column
    reason_start TEXT,              -- export-only column
    reason_end   TEXT,              -- export-only column
    shuffle      INTEGER,           -- export-only column; BOOLEAN stored as 0/1
    skipped      INTEGER            -- export-only column; BOOLEAN stored as 0/1
);

CREATE TABLE IF NOT EXISTS sync_state (
    key    TEXT PRIMARY KEY,
    value  INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_listening_history_played_at
    ON listening_history(played_at DESC);
