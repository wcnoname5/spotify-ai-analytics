SELECT
    COUNT(*) AS total_plays,
    COUNT(DISTINCT track_id) AS unique_tracks,
    COUNT(DISTINCT artist_name) AS unique_artists,
    MIN(played_at) AS earliest_played_at,
    MAX(played_at) AS latest_played_at,
    SUM(ms_played) / 60000 AS total_mins_played,
    CAST(AVG(ms_played) / 60000 AS INTEGER) AS avg_mins_per_play,
    SUM(CASE WHEN ms_played < 30000 THEN 1 ELSE 0 END) * 1.0
        / NULLIF(COUNT(*), 0) AS skip_rate -- skip threshold: plays under 30000ms (30s) count as skipped
FROM listening_history
WHERE (?1 IS NULL OR played_at >= ?1)
  AND (?2 IS NULL OR played_at <= ?2)
