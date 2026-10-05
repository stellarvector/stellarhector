-- What the calendar sync last saw of each occurrence: its start (UTC ISO-8601 string), its title, and the CTFtime event
-- it links to, which makes it a CTF session (NULL for a normal event). NULL until the next sync fills them in.
ALTER TABLE calendar_occurrences ADD COLUMN start_time TEXT;
ALTER TABLE calendar_occurrences ADD COLUMN title TEXT;
ALTER TABLE calendar_occurrences ADD COLUMN ctftime_id INTEGER;

-- Per CTFtime event linked from a calendar session, what the daily CTFtime check last saw (title, start and finish,
-- NULL when CTFtime never knew it) and the start and finish the admins were last told about (NULL until it was first
-- seen on CTFtime). gone is 1 once the admins were told CTFtime no longer knows the event. Times are UTC ISO-8601 strings.
CREATE TABLE ctftime_events (
    ctftime_id INTEGER PRIMARY KEY,
    title TEXT,
    start TEXT,
    finish TEXT,
    checked_at TEXT NOT NULL,
    told_start TEXT,
    told_finish TEXT,
    gone INTEGER NOT NULL DEFAULT 0
);
