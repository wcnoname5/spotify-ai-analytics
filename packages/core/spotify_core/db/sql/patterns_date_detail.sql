-- ?4 = the target local date (YYYY-MM-DD), as picked by patterns_top_date.sql
SELECT COUNT(*) AS play_count,
       SUM(ms_played) / 60000 AS total_mins
FROM listening_history
WHERE date(datetime(played_at, ?3)) = ?4
  AND (?1 IS NULL OR played_at >= ?1)
  AND (?2 IS NULL OR played_at <= ?2)
