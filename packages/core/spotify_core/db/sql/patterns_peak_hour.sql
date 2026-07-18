SELECT CAST(strftime('%H', datetime(played_at, ?3)) AS INTEGER) AS hour,
       COUNT(*) AS cnt
FROM listening_history
WHERE (?1 IS NULL OR played_at >= ?1)
  AND (?2 IS NULL OR played_at <= ?2)
GROUP BY hour
ORDER BY cnt DESC
LIMIT 1
