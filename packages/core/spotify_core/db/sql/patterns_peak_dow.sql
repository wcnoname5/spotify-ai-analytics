SELECT strftime('%w', datetime(played_at, ?3)) AS dow,
       COUNT(*) AS cnt
FROM listening_history
WHERE (?1 IS NULL OR played_at >= ?1)
  AND (?2 IS NULL OR played_at <= ?2)
GROUP BY dow
ORDER BY cnt DESC
LIMIT 1
