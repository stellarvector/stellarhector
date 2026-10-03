-- Who plays each CTF: joined (has the CTF role) or pending (waiting for a moderator, with the message ID of the approval
-- card in the CTF's #bot). joined_at is when they joined or asked to, a UTC ISO-8601 string.
CREATE TABLE ctf_players (
    ctf_id INTEGER NOT NULL REFERENCES ctfs (id),
    user_id INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('joined', 'pending')),
    approval_card_message_id INTEGER,
    joined_at TEXT NOT NULL,
    PRIMARY KEY (ctf_id, user_id)
);
