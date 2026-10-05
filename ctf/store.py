"""Reading and writing the CTFs, their players, categories and challenges in the database."""

import sqlite3
from dataclasses import fields
from datetime import datetime

from core import db
from ctf.models import Category, Challenge, Ctf, NewCtf, Player, PlayerStatus

_TIMES = {
    "start",
    "finish",
    "last_call_at",
    "released_at",
    "locked_at",
    "archived_at",
    "removal_reminded_at",
    "removed_at",
}


def create(ctf: NewCtf) -> Ctf:
    """Raises sqlite3.IntegrityError when a CTF that is not removed already has the same name or CTFtime ID."""
    with db.transaction() as conn:
        cursor = conn.execute(
            "INSERT INTO ctfs (name, ctftime_id, start, finish, role_id, category_id, main_channel_id, bot_channel_id,"
            " guide_message_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                ctf.name,
                ctf.ctftime_id,
                db.time_text(ctf.start),
                db.time_text(ctf.finish),
                ctf.role_id,
                ctf.category_id,
                ctf.main_channel_id,
                ctf.bot_channel_id,
                ctf.guide_message_id,
            ),
        )
        return _ctf(conn.execute("SELECT * FROM ctfs WHERE id = ?", (cursor.lastrowid,)).fetchone())


def get(ctf_id: int) -> Ctf | None:
    """Also returns removed CTFs."""
    with db.transaction() as conn:
        row = conn.execute("SELECT * FROM ctfs WHERE id = ?", (ctf_id,)).fetchone()
    return None if row is None else _ctf(row)


def reread(ctf_id: int) -> Ctf:
    """The CTF as it is stored now, for code that already holds a copy of it. Removing a CTF only marks it, and only a
    failed setup deletes one, so a CTF that was handed around is always still there."""
    ctf = get(ctf_id)
    if ctf is None:
        raise LookupError(f"CTF {ctf_id} is not stored")
    return ctf


def find(name: str | None = None, ctftime_id: int | None = None) -> Ctf | None:
    """Returns the CTF that is not removed and has this name (ignoring case) or this CTFtime ID."""
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT * FROM ctfs WHERE removed_at IS NULL AND (name = ? COLLATE NOCASE OR ctftime_id = ?)"
            " ORDER BY id LIMIT 1",
            (name, ctftime_id),
        ).fetchone()
    return None if row is None else _ctf(row)


def ever_set_up(ctftime_id: int) -> bool:
    """Also counts CTFs that have been removed since."""
    with db.transaction() as conn:
        return conn.execute("SELECT 1 FROM ctfs WHERE ctftime_id = ?", (ctftime_id,)).fetchone() is not None


def find_by_category(category_id: int) -> Ctf | None:
    """Ignores removed CTFs."""
    with db.transaction() as conn:
        row = conn.execute("SELECT * FROM ctfs WHERE removed_at IS NULL AND category_id = ?", (category_id,)).fetchone()
    return None if row is None else _ctf(row)


def managed() -> list[Ctf]:
    """Returns the CTFs that are not removed, ordered by start (those without dates last), then by setup order."""
    with db.transaction() as conn:
        rows = conn.execute("SELECT * FROM ctfs WHERE removed_at IS NULL ORDER BY start IS NULL, start, id").fetchall()
    return [_ctf(row) for row in rows]


def ctftime_ids_not_locked() -> list[int]:
    """Returns the CTFtime IDs of the CTFs that are neither removed nor locked, whose dates can still change which
    steps run."""
    with db.transaction() as conn:
        rows = conn.execute(
            "SELECT ctftime_id FROM ctfs WHERE removed_at IS NULL AND locked_at IS NULL"
            " AND ctftime_id IS NOT NULL ORDER BY ctftime_id"
        ).fetchall()
    return [row["ctftime_id"] for row in rows]


def set_dates(ctftime_id: int, start: datetime | None, finish: datetime | None) -> None:
    """Updates only the CTF that is not removed; does nothing when there is none."""
    with db.transaction() as conn:
        conn.execute(
            "UPDATE ctfs SET start = ?, finish = ? WHERE ctftime_id = ? AND removed_at IS NULL",
            (db.time_text(start), db.time_text(finish), ctftime_id),
        )


def set_join_message(ctf_id: int, channel_id: int, message_id: int) -> None:
    with db.transaction() as conn:
        conn.execute(
            "UPDATE ctfs SET join_channel_id = ?, join_message_id = ? WHERE id = ?", (channel_id, message_id, ctf_id)
        )


def mark_last_call(ctf_id: int, channel_id: int, message_id: int, at: datetime) -> None:
    """Also stores the join message that the last call posted again."""
    with db.transaction() as conn:
        conn.execute(
            "UPDATE ctfs SET join_channel_id = ?, join_message_id = ?, last_call_at = ? WHERE id = ?",
            (channel_id, message_id, db.time_text(at), ctf_id),
        )


def mark_released(ctf_id: int, at: datetime) -> bool:
    """Returns False when the CTF was already released, so that only one of two concurrent runs goes ahead."""
    with db.transaction() as conn:
        cursor = conn.execute(
            "UPDATE ctfs SET released_at = ? WHERE id = ? AND released_at IS NULL", (db.time_text(at), ctf_id)
        )
        return cursor.rowcount == 1


def mark_locked(ctf_id: int, at: datetime) -> bool:
    """Returns False when the CTF was already locked, so that only one of two concurrent runs goes ahead."""
    with db.transaction() as conn:
        cursor = conn.execute(
            "UPDATE ctfs SET locked_at = ? WHERE id = ? AND locked_at IS NULL", (db.time_text(at), ctf_id)
        )
        return cursor.rowcount == 1


def mark_removal_reminded(ctf_id: int, at: datetime) -> None:
    with db.transaction() as conn:
        conn.execute("UPDATE ctfs SET removal_reminded_at = ? WHERE id = ?", (db.time_text(at), ctf_id))


def set_overview_message(ctf_id: int, message_id: int) -> None:
    with db.transaction() as conn:
        conn.execute("UPDATE ctfs SET overview_message_id = ? WHERE id = ?", (message_id, ctf_id))


def delete(ctf_id: int) -> None:
    """Deletes the CTF with its players, categories and challenges, as if it was never set up. Unlike `mark_removed`,
    this leaves no trace."""
    with db.transaction() as conn:
        conn.execute("DELETE FROM ctf_players WHERE ctf_id = ?", (ctf_id,))
        conn.execute("DELETE FROM ctf_challenges WHERE ctf_id = ?", (ctf_id,))
        conn.execute("DELETE FROM ctf_categories WHERE ctf_id = ?", (ctf_id,))
        conn.execute("DELETE FROM ctfs WHERE id = ?", (ctf_id,))


def mark_archived(ctf_id: int, at: datetime) -> None:
    with db.transaction() as conn:
        conn.execute("UPDATE ctfs SET archived_at = ? WHERE id = ?", (db.time_text(at), ctf_id))


def mark_removed(ctf_id: int, at: datetime) -> None:
    with db.transaction() as conn:
        conn.execute("UPDATE ctfs SET removed_at = ? WHERE id = ?", (db.time_text(at), ctf_id))


def add_player(ctf_id: int, user_id: int, at: datetime) -> None:
    """A user who is already on the player list is set to joined, their approval card is cleared, and they keep their
    original join time."""
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO ctf_players (ctf_id, user_id, status, joined_at) VALUES (?, ?, 'joined', ?)"
            " ON CONFLICT (ctf_id, user_id) DO UPDATE SET status = 'joined', approval_card_message_id = NULL",
            (ctf_id, user_id, db.time_text(at)),
        )


def add_pending_player(ctf_id: int, user_id: int, at: datetime) -> None:
    """Raises sqlite3.IntegrityError when the user is already on the player list."""
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO ctf_players (ctf_id, user_id, status, joined_at) VALUES (?, ?, 'pending', ?)",
            (ctf_id, user_id, db.time_text(at)),
        )


def set_approval_card(ctf_id: int, user_id: int, message_id: int) -> bool:
    """Returns False, and stores nothing, when the user is no longer pending."""
    with db.transaction() as conn:
        cursor = conn.execute(
            "UPDATE ctf_players SET approval_card_message_id = ? WHERE ctf_id = ? AND user_id = ?"
            " AND status = 'pending'",
            (message_id, ctf_id, user_id),
        )
        return cursor.rowcount == 1


def reopen_request(ctf_id: int, user_id: int, at: datetime, message_id: int) -> None:
    """Sets the user to pending on this approval card, whether or not they are on the player list already."""
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO ctf_players (ctf_id, user_id, status, approval_card_message_id, joined_at)"
            " VALUES (?, ?, 'pending', ?, ?) ON CONFLICT (ctf_id, user_id) DO UPDATE SET status = 'pending',"
            " approval_card_message_id = excluded.approval_card_message_id, joined_at = excluded.joined_at",
            (ctf_id, user_id, message_id, db.time_text(at)),
        )


def remove_player(ctf_id: int, user_id: int) -> None:
    with db.transaction() as conn:
        conn.execute("DELETE FROM ctf_players WHERE ctf_id = ? AND user_id = ?", (ctf_id, user_id))


def player(ctf_id: int, user_id: int) -> Player | None:
    with db.transaction() as conn:
        row = conn.execute("SELECT * FROM ctf_players WHERE ctf_id = ? AND user_id = ?", (ctf_id, user_id)).fetchone()
    return None if row is None else _player(row)


def players(ctf_id: int) -> list[Player]:
    with db.transaction() as conn:
        rows = conn.execute(
            "SELECT * FROM ctf_players WHERE ctf_id = ? ORDER BY joined_at, user_id", (ctf_id,)
        ).fetchall()
    return [_player(row) for row in rows]


def times_joined(user_id: int) -> int:
    """Does not count CTFs where the user is still pending."""
    with db.transaction() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM ctf_players WHERE user_id = ? AND status = 'joined'", (user_id,)
        ).fetchone()[0]


def add_category(ctf_id: int, slug: str, channel_id: int) -> None:
    """When the CTF already has a category with this slug, only its channel is replaced."""
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO ctf_categories (ctf_id, slug, channel_id) VALUES (?, ?, ?)"
            " ON CONFLICT (ctf_id, slug) DO UPDATE SET channel_id = excluded.channel_id",
            (ctf_id, slug, channel_id),
        )


def categories(ctf_id: int) -> list[Category]:
    with db.transaction() as conn:
        rows = conn.execute(
            "SELECT slug, channel_id FROM ctf_categories WHERE ctf_id = ? ORDER BY slug", (ctf_id,)
        ).fetchall()
    return [Category(row["slug"], row["channel_id"]) for row in rows]


def category_by_channel(ctf_id: int, channel_id: int) -> Category | None:
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT slug, channel_id FROM ctf_categories WHERE ctf_id = ? AND channel_id = ?", (ctf_id, channel_id)
        ).fetchone()
    return None if row is None else Category(row["slug"], row["channel_id"])


def add_challenge(ctf_id: int, category: str, slug: str, thread_id: int) -> None:
    """Stores a new challenge as unsolved. An existing challenge only gets the new thread and keeps its solved
    state."""
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO ctf_challenges (ctf_id, category, slug, thread_id) VALUES (?, ?, ?, ?)"
            " ON CONFLICT (ctf_id, category, slug) DO UPDATE SET thread_id = excluded.thread_id",
            (ctf_id, category, slug, thread_id),
        )


def challenge(ctf_id: int, category: str, slug: str) -> Challenge | None:
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT * FROM ctf_challenges WHERE ctf_id = ? AND category = ? AND slug = ?", (ctf_id, category, slug)
        ).fetchone()
    return None if row is None else _challenge(row)


def challenge_by_thread(ctf_id: int, thread_id: int) -> Challenge | None:
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT * FROM ctf_challenges WHERE ctf_id = ? AND thread_id = ?", (ctf_id, thread_id)
        ).fetchone()
    return None if row is None else _challenge(row)


def challenges(ctf_id: int) -> list[Challenge]:
    with db.transaction() as conn:
        rows = conn.execute(
            "SELECT * FROM ctf_challenges WHERE ctf_id = ? ORDER BY category, slug", (ctf_id,)
        ).fetchall()
    return [_challenge(row) for row in rows]


def set_solved(ctf_id: int, category: str, slug: str, solved: bool) -> bool:
    """Returns False when the challenge already had this state, so that only one of two concurrent runs goes ahead."""
    with db.transaction() as conn:
        cursor = conn.execute(
            "UPDATE ctf_challenges SET solved = ? WHERE ctf_id = ? AND category = ? AND slug = ? AND solved != ?",
            (int(solved), ctf_id, category, slug, int(solved)),
        )
        return cursor.rowcount == 1


def _challenge(row: sqlite3.Row) -> Challenge:
    return Challenge(row["category"], row["slug"], row["thread_id"], bool(row["solved"]))


def _player(row: sqlite3.Row) -> Player:
    return Player(
        user_id=row["user_id"],
        status=PlayerStatus(row["status"]),
        approval_card_message_id=row["approval_card_message_id"],
        joined_at=db.parse_time(row["joined_at"]),
    )


def _ctf(row: sqlite3.Row) -> Ctf:
    return Ctf(
        **{
            field.name: db.parse_time(row[field.name]) if field.name in _TIMES else row[field.name]
            for field in fields(Ctf)
        }
    )
