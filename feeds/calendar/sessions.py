"""CTF sessions: calendar occurrences that link to a CTFtime event, i.e. the on-campus nights of a CTF."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from core import db


@dataclass(frozen=True)
class Session:
    title: str
    start: datetime
    end: datetime


class Period(Protocol):
    @property
    def start(self) -> datetime: ...

    @property
    def finish(self) -> datetime: ...


def linked_sessions() -> dict[int, list[Session]]:
    """The sessions per CTFtime event, sorted by start. Only the occurrences that the calendar sync created an event
    for are known, so sessions beyond its lookahead are missing."""
    sessions = defaultdict(list)
    with db.transaction() as conn:
        rows = conn.execute(
            "SELECT ctftime_id, title, start_time, end_time FROM calendar_occurrences "
            "WHERE ctftime_id IS NOT NULL AND start_time IS NOT NULL ORDER BY start_time"
        ).fetchall()
    for row in rows:
        sessions[row["ctftime_id"]].append(
            Session(row["title"], db.parse_time(row["start_time"]), db.parse_time(row["end_time"]))
        )
    return dict(sorted(sessions.items()))


def overlaps(session: Session, ctf: Period) -> bool:
    """Whether the session falls at least partly within the CTF."""
    return session.start < ctf.finish and session.end > ctf.start
