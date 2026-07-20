INSERT OR IGNORE INTO reports
    (id, style, period_type, start_date, end_date,
     provider, model, generated_at, revision_count, report_text, synced)
VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11)
