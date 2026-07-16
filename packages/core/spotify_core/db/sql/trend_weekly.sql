-- Monday-based weeks: bucket label is the ISO date of the week's Monday.
SELECT date(
           datetime(played_at, ?3),
           '-' || ((strftime('%w', datetime(played_at, ?3)) + 6) % 7) || ' days'
       ) AS bucket,
       SUM(ms_played) / 60000 AS total_mins,
       COUNT(*) AS play_count
FROM listening_history
WHERE (?1 IS NULL OR played_at >= ?1)
  AND (?2 IS NULL OR played_at <= ?2)
GROUP BY bucket
ORDER BY bucket
