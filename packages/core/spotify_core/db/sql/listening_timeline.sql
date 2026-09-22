-- One row per play, shaped for a Gantt bar: [started_local, started_local + ms_played].
-- played_at is the END of playback, not the start
SELECT track_name,
       artist_name,
       album_name,
       ms_played,
       datetime(played_at, '-' || (ms_played / 1000) || ' seconds', ?3) AS started_local
FROM listening_history
WHERE (?1 IS NULL OR played_at >= ?1)
  AND (?2 IS NULL OR played_at <= ?2)
  AND ms_played > 0
ORDER BY played_at
