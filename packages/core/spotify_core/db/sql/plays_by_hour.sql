SELECT CAST(strftime('%H', datetime(played_at, ?3)) AS INTEGER) AS hour,
       COUNT(*) AS play_count,
       SUM(ms_played) / 60000 AS total_mins
FROM listening_history
WHERE (?1 IS NULL OR played_at >= ?1)
  AND (?2 IS NULL OR played_at <= ?2)
GROUP BY hour
ORDER BY hour
