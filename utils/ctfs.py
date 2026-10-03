from dataclasses import dataclass, fields
from datetime import datetime

from core import db


@dataclass(frozen=True)
class NewCtf:
    """A CTF whose Discord objects were just created, to be stored with create."""
    name: str
    ctftime_id: int | None
    start: datetime | None
    finish: datetime | None
    role_id: int
    category_id: int
    main_channel_id: int
    bot_channel_id: int
    guide_message_id: int


@dataclass(frozen=True)
class Ctf(NewCtf):
    """A stored CTF: what it was created with, where its join message is (None when it was not posted), and when each
    lifecycle step was done (None until it is)."""
    id: int
    join_channel_id: int | None
    join_message_id: int | None
    last_call_at: datetime | None
    released_at: datetime | None
    locked_at: datetime | None
    archived_at: datetime | None
    removal_reminded_at: datetime | None
    removed_at: datetime | None


_TIMES = {"start", "finish", "last_call_at", "released_at", "locked_at", "archived_at", "removal_reminded_at",
          "removed_at"}


def create(ctf):
    """Store the NewCtf and return it as a Ctf.

    Raises sqlite3.IntegrityError when a CTF that is not removed already has its name or CTFtime ID.
    """
    with db.transaction() as conn:
        cursor = conn.execute(
            "INSERT INTO ctfs (name, ctftime_id, start, finish, role_id, category_id, main_channel_id, bot_channel_id,"
            " guide_message_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (ctf.name, ctf.ctftime_id, db.time_text(ctf.start), db.time_text(ctf.finish), ctf.role_id,
             ctf.category_id, ctf.main_channel_id, ctf.bot_channel_id, ctf.guide_message_id))
        return _ctf(conn.execute("SELECT * FROM ctfs WHERE id = ?", (cursor.lastrowid,)).fetchone())


def get(ctf_id):
    """The CTF with this ID, also when it is removed, or None."""
    with db.transaction() as conn:
        row = conn.execute("SELECT * FROM ctfs WHERE id = ?", (ctf_id,)).fetchone()
    return None if row is None else _ctf(row)


def find(name=None, ctftime_id=None):
    """The CTF that is not removed with this name (ignoring case) or this CTFtime ID, or None."""
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT * FROM ctfs WHERE removed_at IS NULL AND (name = ? COLLATE NOCASE OR ctftime_id = ?)"
            " ORDER BY id LIMIT 1",
            (name, ctftime_id)).fetchone()
    return None if row is None else _ctf(row)


def find_by_category(category_id):
    """The CTF that is not removed whose Discord category has this ID, or None."""
    with db.transaction() as conn:
        row = conn.execute("SELECT * FROM ctfs WHERE removed_at IS NULL AND category_id = ?",
                           (category_id,)).fetchone()
    return None if row is None else _ctf(row)


def set_join_message(ctf_id, channel_id, message_id):
    """Remember where the CTF's join message was posted."""
    with db.transaction() as conn:
        conn.execute("UPDATE ctfs SET join_channel_id = ?, join_message_id = ? WHERE id = ?",
                     (channel_id, message_id, ctf_id))


def mark_last_call(ctf_id, channel_id, message_id, at):
    """Remember that the last call was done at the time at, with the join message posted anew in that channel."""
    with db.transaction() as conn:
        conn.execute("UPDATE ctfs SET join_channel_id = ?, join_message_id = ?, last_call_at = ? WHERE id = ?",
                     (channel_id, message_id, db.time_text(at), ctf_id))


def delete(ctf_id):
    """Forget the CTF and its player list entirely, as if it was never set up (unlike mark_removed)."""
    with db.transaction() as conn:
        conn.execute("DELETE FROM ctf_players WHERE ctf_id = ?", (ctf_id,))
        conn.execute("DELETE FROM ctfs WHERE id = ?", (ctf_id,))


def mark_archived(ctf_id, at):
    with db.transaction() as conn:
        conn.execute("UPDATE ctfs SET archived_at = ? WHERE id = ?", (db.time_text(at), ctf_id))


def mark_removed(ctf_id, at):
    with db.transaction() as conn:
        conn.execute("UPDATE ctfs SET removed_at = ? WHERE id = ?", (db.time_text(at), ctf_id))


@dataclass(frozen=True)
class Player:
    """Someone on a CTF's player list: status is "joined" or "pending" (waiting for a moderator's approval card)."""
    user_id: int
    status: str
    approval_card_message_id: int | None
    joined_at: datetime


def add_player(ctf_id, user_id, at):
    """Put the user on the CTF's player list as joined at the time at. Someone already on it is set to joined (no
    longer waiting for an approval card), and keeps their first join time."""
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO ctf_players (ctf_id, user_id, status, joined_at) VALUES (?, ?, 'joined', ?)"
            " ON CONFLICT (ctf_id, user_id) DO UPDATE SET status = 'joined', approval_card_message_id = NULL",
            (ctf_id, user_id, db.time_text(at)))


def add_pending_player(ctf_id, user_id, at):
    """Put the user on the CTF's player list as pending, asking to join at the time at, until a moderator decides.
    Raises sqlite3.IntegrityError when they are on it already."""
    with db.transaction() as conn:
        conn.execute("INSERT INTO ctf_players (ctf_id, user_id, status, joined_at) VALUES (?, ?, 'pending', ?)",
                     (ctf_id, user_id, db.time_text(at)))


def set_approval_card(ctf_id, user_id, message_id):
    """Remember the approval card posted for the user's pending request to join the CTF."""
    with db.transaction() as conn:
        conn.execute("UPDATE ctf_players SET approval_card_message_id = ? WHERE ctf_id = ? AND user_id = ?",
                     (message_id, ctf_id, user_id))


def reopen_request(ctf_id, user_id, at, message_id):
    """Put the user back on the CTF's player list as pending since at, waiting on the approval card with this message
    ID, whether they are on the list now or not."""
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO ctf_players (ctf_id, user_id, status, approval_card_message_id, joined_at)"
            " VALUES (?, ?, 'pending', ?, ?) ON CONFLICT (ctf_id, user_id) DO UPDATE SET status = 'pending',"
            " approval_card_message_id = excluded.approval_card_message_id, joined_at = excluded.joined_at",
            (ctf_id, user_id, message_id, db.time_text(at)))


def remove_player(ctf_id, user_id):
    """Take the user off the CTF's player list; nothing happens when they are not on it."""
    with db.transaction() as conn:
        conn.execute("DELETE FROM ctf_players WHERE ctf_id = ? AND user_id = ?", (ctf_id, user_id))


def player(ctf_id, user_id):
    """The user's entry on the CTF's player list, or None when they are not on it."""
    with db.transaction() as conn:
        row = conn.execute("SELECT * FROM ctf_players WHERE ctf_id = ? AND user_id = ?", (ctf_id, user_id)).fetchone()
    return None if row is None else _player(row)


def players(ctf_id):
    """The CTF's player list, in the order they joined."""
    with db.transaction() as conn:
        rows = conn.execute("SELECT * FROM ctf_players WHERE ctf_id = ? ORDER BY joined_at, user_id",
                            (ctf_id,)).fetchall()
    return [_player(row) for row in rows]


def times_joined(user_id):
    """How many CTFs the user has joined (not counting those where they wait for a moderator)."""
    with db.transaction() as conn:
        return conn.execute("SELECT COUNT(*) FROM ctf_players WHERE user_id = ? AND status = 'joined'",
                            (user_id,)).fetchone()[0]


def _player(row):
    return Player(user_id=row["user_id"], status=row["status"],
                  approval_card_message_id=row["approval_card_message_id"], joined_at=db.parse_time(row["joined_at"]))


def _ctf(row):
    return Ctf(**{field.name: db.parse_time(row[field.name]) if field.name in _TIMES else row[field.name]
                  for field in fields(Ctf)})
