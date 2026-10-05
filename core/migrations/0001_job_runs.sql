-- Last successful run per scheduled job; last_run_at is a UTC ISO-8601 string
CREATE TABLE job_runs (
    name TEXT PRIMARY KEY,
    last_run_at TEXT
);
