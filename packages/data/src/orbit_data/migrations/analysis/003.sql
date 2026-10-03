-- The process that owns a running analysis; a killed worker's run is failed by the next start.
ALTER TABLE analysis_run ADD COLUMN owner_pid INTEGER;
