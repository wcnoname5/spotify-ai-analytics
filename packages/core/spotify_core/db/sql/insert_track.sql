INSERT OR IGNORE INTO listening_history
    (id, track_id, track_name, artist_name, album_name,
     played_at, ms_played, source,
     platform, conn_country, reason_start, reason_end, shuffle, skipped)
VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14)
