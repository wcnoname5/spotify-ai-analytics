-- Delete one saved report. D1 is deleted first; this is the cache half.
DELETE FROM reports WHERE id = ?1;
