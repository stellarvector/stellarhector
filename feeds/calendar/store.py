"""The calendar occurrences the bot created a Discord event for."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from core import db
from feeds.calendar.parse import Occurrence, OccurrenceKey

# Selects the row of an OccurrenceKey; the start column holds its slot
_WHERE_KEY = "uid = ? AND start = ?"


@dataclass(frozen=True)
class StoredOccurrence:
    discord_event_id: int
    # None when the event was not announced
    announcement_message_id: int | None
    # The end the occurrence had in the calendar at the last sync
    end: datetime


def stored_occurrences() -> dict[OccurrenceKey, StoredOccurrence]:
    with db.transaction() as conn:
        return {
            OccurrenceKey(row["uid"], row["start"]): StoredOccurrence(
                row["discord_event_id"], row["announcement_message_id"], db.parse_time(row["end_time"])
            )
            for row in conn.execute(
                "SELECT uid, start, discord_event_id, announcement_message_id, end_time FROM calendar_occurrences"
            )
        }


def add_event(key: OccurrenceKey, event_id: int, end: datetime) -> None:
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO calendar_occurrences (uid, start, discord_event_id, end_time) VALUES (?, ?, ?, ?)",
            (*key, event_id, db.time_text(end)),
        )


def replace_event(key: OccurrenceKey, event_id: int, end: datetime) -> None:
    with db.transaction() as conn:
        conn.execute(
            f"UPDATE calendar_occurrences SET discord_event_id = ?, end_time = ? WHERE {_WHERE_KEY}",
            (event_id, db.time_text(end), *key),
        )


def set_end(key: OccurrenceKey, end: datetime) -> None:
    with db.transaction() as conn:
        conn.execute(f"UPDATE calendar_occurrences SET end_time = ? WHERE {_WHERE_KEY}", (db.time_text(end), *key))


def set_announcement(key: OccurrenceKey, message_id: int) -> None:
    with db.transaction() as conn:
        conn.execute(
            f"UPDATE calendar_occurrences SET announcement_message_id = ? WHERE {_WHERE_KEY}", (message_id, *key)
        )


def forget(key: OccurrenceKey) -> None:
    with db.transaction() as conn:
        conn.execute(f"DELETE FROM calendar_occurrences WHERE {_WHERE_KEY}", key)


def remember_details(occurrences: list[Occurrence], title: Callable[[Occurrence], str]) -> None:
    """Store the current start, title and CTFtime link of each occurrence that has an event, as the CTF sessions are
    read from them. When an occurrence is listed twice, the first one wins."""
    remembered = set()
    with db.transaction() as conn:
        for occurrence in occurrences:
            if occurrence.key in remembered:
                continue
            remembered.add(occurrence.key)
            values = (db.time_text(occurrence.start), title(occurrence), occurrence.ctftime_id)
            # Only written when something changed, so a sync without changes writes nothing
            conn.execute(
                f"UPDATE calendar_occurrences SET start_time = ?, title = ?, ctftime_id = ? WHERE {_WHERE_KEY}"
                " AND (start_time IS NOT ? OR title IS NOT ? OR ctftime_id IS NOT ?)",
                (*values, *occurrence.key, *values),
            )
