SELECT COUNT(*) * 1.0 / NULLIF(COUNT(DISTINCT date(datetime(played_at, ?3))), 0) AS avg
FROM listening_history
WHERE (?1 IS NULL OR played_at >= ?1)
  AND (?2 IS NULL OR played_at <= ?2)
