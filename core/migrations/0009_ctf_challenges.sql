-- The challenges of each CTF made with /create-challenge: the category (its slug in ctf_categories) and the challenge's
-- slug, the thread made for it in the category's channel, and whether it is solved (0 or 1).
CREATE TABLE ctf_challenges (
    ctf_id INTEGER NOT NULL REFERENCES ctfs (id),
    category TEXT NOT NULL,
    slug TEXT NOT NULL,
    thread_id INTEGER NOT NULL,
    solved INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (ctf_id, category, slug)
);
