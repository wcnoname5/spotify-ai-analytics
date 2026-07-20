-- Copied from packages/core/spotify_core/db/sql/schema.sql (reports table).
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
