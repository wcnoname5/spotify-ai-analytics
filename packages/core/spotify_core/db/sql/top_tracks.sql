SELECT track_id,
       track_name,
       artist_name,
       COUNT(*) AS play_count,
       SUM(ms_played) / 60000 AS total_mins
FROM listening_history
WHERE track_name IS NOT NULL
  AND (?1 IS NULL OR played_at >= ?1)
  AND (?2 IS NULL OR played_at <= ?2)
GROUP BY track_id
ORDER BY play_count DESC, total_mins DESC
LIMIT ?3
