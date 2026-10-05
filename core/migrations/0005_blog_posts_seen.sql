-- The guid of every blog feed item the blog check has seen, and when it was first seen (UTC ISO-8601 string). An item
-- is in here once it has a forum post in #learning, or was in the feed at the very first check, which posts nothing.
CREATE TABLE blog_posts_seen (
    guid TEXT PRIMARY KEY,
    seen_at TEXT NOT NULL
);
