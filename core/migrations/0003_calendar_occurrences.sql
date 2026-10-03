-- The Discord event (and its announcement) the calendar sync created per calendar occurrence.
-- An occurrence is its ICS UID plus, in start, its slot in a recurring series (RECURRENCE-ID) as a UTC ISO-8601 string,
-- or the empty string for an event that does not recur. end_time is the end the occurrence had in the calendar at the
-- last sync, a UTC ISO-8601 string: an occurrence gone from the feed is over when its end has passed, else cancelled.
-- Discord events not in here are never touched.
CREATE TABLE calendar_occurrences (
    uid TEXT NOT NULL,
    start TEXT NOT NULL,
    discord_event_id INTEGER NOT NULL,
    announcement_message_id INTEGER,
    end_time TEXT NOT NULL,
    PRIMARY KEY (uid, start)
);
