SELECT strftime('%Y-%m', datetime(played_at, ?3)) AS bucket,
       SUM(ms_played) / 60000 AS total_mins,
       COUNT(*) AS play_count
FROM listening_history
WHERE (?1 IS NULL OR played_at >= ?1)
  AND (?2 IS NULL OR played_at <= ?2)
GROUP BY bucket
ORDER BY bucket
