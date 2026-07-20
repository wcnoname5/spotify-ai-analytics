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

CREATE TABLE IF NOT EXISTS reports (
    id             TEXT PRIMARY KEY,           -- uuid4, minted by whoever saves; makes push idempotent
    style          TEXT NOT NULL,
    period_type    TEXT NOT NULL,              -- weekly | monthly | quarterly
    start_date     TEXT NOT NULL,              -- YYYY-MM-DD
    end_date       TEXT NOT NULL,
    provider       TEXT NOT NULL,
    model          TEXT NOT NULL,
    generated_at   TEXT NOT NULL,              -- UTC ISO
    revision_count INTEGER NOT NULL DEFAULT 0,
    report_text    TEXT NOT NULL,
    synced         INTEGER NOT NULL DEFAULT 0  -- meaningful locally only; D1 never reads it
);

CREATE INDEX IF NOT EXISTS idx_reports_generated_at ON reports(generated_at);
