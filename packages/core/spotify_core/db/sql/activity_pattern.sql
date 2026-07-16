-- Time segments are local hour-of-day ranges: 0-6, 7-12, 13-18, else (19-23).
SELECT
    strftime('%w', datetime(played_at, ?3)) AS dow,
    CASE
        WHEN CAST(strftime('%H', datetime(played_at, ?3)) AS INTEGER) BETWEEN 0 AND 6 THEN '00:00-06:59'
        WHEN CAST(strftime('%H', datetime(played_at, ?3)) AS INTEGER) BETWEEN 7 AND 12 THEN '07:00-12:59'
        WHEN CAST(strftime('%H', datetime(played_at, ?3)) AS INTEGER) BETWEEN 13 AND 18 THEN '13:00-18:59'
        ELSE '19:00-23:59'
    END AS segment,
    SUM(ms_played) / 60000 AS total_mins
FROM listening_history
WHERE (?1 IS NULL OR played_at >= ?1)
  AND (?2 IS NULL OR played_at <= ?2)
GROUP BY dow, segment
