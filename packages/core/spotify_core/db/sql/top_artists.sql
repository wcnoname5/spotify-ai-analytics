SELECT artist_name,
       SUM(ms_played) / 60000 AS total_mins,
       COUNT(*) AS play_count
FROM listening_history
WHERE artist_name IS NOT NULL
  AND (?1 IS NULL OR played_at >= ?1)
  AND (?2 IS NULL OR played_at <= ?2)
GROUP BY artist_name
ORDER BY total_mins DESC
LIMIT ?3
