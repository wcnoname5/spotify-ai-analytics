SELECT id, style, period_type, start_date, end_date,
       provider, model, generated_at, revision_count, report_text, synced
FROM reports WHERE id = ?1
