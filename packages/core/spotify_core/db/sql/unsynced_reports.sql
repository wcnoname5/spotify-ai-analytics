SELECT id, style, period_type, start_date, end_date,
       provider, model, generated_at, revision_count, report_text
FROM reports WHERE synced = 0 ORDER BY generated_at
