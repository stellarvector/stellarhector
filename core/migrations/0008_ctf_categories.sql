-- The challenge categories of each CTF made with /add-category: the slug, which is also the name of its channel in the
-- CTF's category, and that channel's ID.
CREATE TABLE ctf_categories (
    ctf_id INTEGER NOT NULL REFERENCES ctfs (id),
    slug TEXT NOT NULL,
    channel_id INTEGER NOT NULL,
    PRIMARY KEY (ctf_id, slug)
);
