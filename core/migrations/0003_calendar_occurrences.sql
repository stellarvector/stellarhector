-- The Discord event (and its announcement) the calendar sync created per calendar occurrence.
-- An occurrence is its ICS UID plus its start as a UTC ISO-8601 string. Discord events not in here are never touched.
CREATE TABLE calendar_occurrences (
    uid TEXT NOT NULL,
    start TEXT NOT NULL,
    discord_event_id INTEGER NOT NULL,
    announcement_message_id INTEGER,
    PRIMARY KEY (uid, start)
);
