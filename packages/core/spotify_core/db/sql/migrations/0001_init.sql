-- Hand-maintained since scripts/gen_d1_migration.py was retired. Keep in step with schema.sql.
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

CREATE TABLE IF NOT EXISTS spotify_tokens (
    user_id       TEXT PRIMARY KEY,
    access_token  TEXT NOT NULL,
    refresh_token TEXT NOT NULL,
    expires_at    DATETIME NOT NULL,
    scopes        TEXT
);

CREATE TABLE IF NOT EXISTS sync_state (
    key    TEXT PRIMARY KEY,
    value  INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_listening_history_played_at
    ON listening_history(played_at DESC);
