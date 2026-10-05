-- Start of the current run of failures (UTC ISO-8601, NULL while the job works) and whether it was alerted
ALTER TABLE job_runs ADD COLUMN failing_since TEXT;
ALTER TABLE job_runs ADD COLUMN alerted INTEGER NOT NULL DEFAULT 0;
