-- Every CTF set up with /setup-ctf (or by the automatic timeline): its name as typed, the CTFtime event it is (NULL when
-- set up without one, so it never gets automatic steps) with that event's start and finish, the Discord objects made
-- for it (join_channel_id and join_message_id: the join message in #upcoming-ctfs, NULL when it was not posted), and
-- when each lifecycle step was done (NULL until it is). Times are UTC ISO-8601 strings.
-- A removed CTF keeps its row; only one CTF that is not removed can have a given name (ignoring case) or CTFtime ID.
CREATE TABLE ctfs (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    ctftime_id INTEGER,
    start TEXT,
    finish TEXT,
    role_id INTEGER NOT NULL,
    category_id INTEGER NOT NULL,
    main_channel_id INTEGER NOT NULL,
    bot_channel_id INTEGER NOT NULL,
    guide_message_id INTEGER NOT NULL,
    join_channel_id INTEGER,
    join_message_id INTEGER,
    last_call_at TEXT,
    released_at TEXT,
    locked_at TEXT,
    archived_at TEXT,
    removal_reminded_at TEXT,
    removed_at TEXT
);

CREATE UNIQUE INDEX ctfs_name ON ctfs (name COLLATE NOCASE) WHERE removed_at IS NULL;
CREATE UNIQUE INDEX ctfs_ctftime_id ON ctfs (ctftime_id) WHERE removed_at IS NULL AND ctftime_id IS NOT NULL;
