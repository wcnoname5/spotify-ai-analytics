SELECT id, style, period_type, start_date, end_date,
       provider, model, generated_at, revision_count
FROM reports ORDER BY generated_at DESC
