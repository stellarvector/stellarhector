-- The Discord event (and its announcement) the calendar sync created per calendar occurrence.
-- An occurrence is its ICS UID plus, in start, its slot in a recurring series (RECURRENCE-ID) as a UTC ISO-8601 string,
-- or the empty string for an event that does not recur. Discord events not in here are never touched.
CREATE TABLE calendar_occurrences (
    uid TEXT NOT NULL,
    start TEXT NOT NULL,
    discord_event_id INTEGER NOT NULL,
    announcement_message_id INTEGER,
    PRIMARY KEY (uid, start)
);
