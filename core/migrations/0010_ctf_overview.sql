-- The challenge overview pinned in each CTF's main channel, posted when its first challenge is created (NULL until
-- then).
ALTER TABLE ctfs ADD COLUMN overview_message_id INTEGER;
