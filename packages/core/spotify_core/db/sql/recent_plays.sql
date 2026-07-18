SELECT track_name,
       artist_name,
       album_name,
       played_at,
       ms_played,
       track_id
FROM listening_history
WHERE (?1 IS NULL OR played_at >= ?1)
  AND (?2 IS NULL OR played_at <= ?2)
ORDER BY played_at DESC
LIMIT ?3
