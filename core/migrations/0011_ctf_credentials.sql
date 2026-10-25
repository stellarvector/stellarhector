-- The credentials message posted with /post-credentials in each CTF's main channel, deleted again before the CTF is
-- released (NULL when there is none).
ALTER TABLE ctfs ADD COLUMN credentials_message_id INTEGER;
