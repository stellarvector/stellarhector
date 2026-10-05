"""The daily check of CTFs on CTFtime: tells the staff when a CTF's dates change, when it disappears from CTFtime, or
when its calendar sessions fall outside it."""

import logging
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, replace
from datetime import datetime

import discord

import core.db as db
from feeds import ctftime
from feeds.calendar.sessions import Session, linked_sessions, overlaps
from utils.text import cut, period
from utils.unfinished import UnfinishedWork

log = logging.getLogger("bot")

# Keeps alerts well under Discord's 2000 characters
SESSION_LIMIT = 5
TITLE_LIMIT = 100

# The alerts and stores of checks that were stopped halfway
_unfinished = UnfinishedWork()

Alert = Callable[[int, str], Awaitable[None]]
DatesChanged = Callable[[int, datetime, datetime], None]
GetEvent = Callable[[int], Awaitable[ctftime.Event | None]]


@dataclass(frozen=True)
class Record:
    """What is stored for a CTFtime event: its data at the last check, and the dates the staff were last told about.
    `title`, `start` and `finish` are None when CTFtime never knew the event."""

    ctftime_id: int
    title: str | None
    start: datetime | None
    finish: datetime | None
    told_start: datetime | None
    told_finish: datetime | None
    # Set once the staff were told CTFtime no longer knows the event
    gone: bool = False


@dataclass(frozen=True)
class DateCheck:
    # None when there is nothing to tell
    alert: str | None
    # Stored once the alert is posted
    record: Record


@dataclass(frozen=True)
class CtftimeCheckResult:
    checked: int = 0
    alerts: int = 0
    # CTFs CTFtime could not be asked about
    skipped: int = 0


def compare_with_ctftime(
    ctftime_id: int, stored: Record | None, event: ctftime.Event | None, sessions: list[Session]
) -> DateCheck:
    """What to tell the staff about a CTFtime event, given what was stored at the last check (None the first time) and
    what CTFtime says now (None when it doesn't know the event)."""
    if event is None:
        return _gone(ctftime_id, stored, sessions)

    record = Record(
        ctftime_id, event.title, event.start, event.finish, told_start=event.start, told_finish=event.finish
    )
    all_overlap = all(overlaps(session, event) for session in sessions)
    ctf = _ctf(ctftime_id, event.title)

    if stored is None or stored.told_start is None or stored.told_finish is None:
        if all_overlap:
            return DateCheck(None, record)
        # Probably a typo in the calendar
        return DateCheck(
            f":warning: Not every calendar session of {ctf} falls within the CTF, which runs"
            f" {period(event.start, event.finish)} on CTFtime:\n{_sessions(sessions, event)}",
            record,
        )

    if (stored.told_start, stored.told_finish) == (event.start, event.finish):
        return DateCheck(None, record)

    if not sessions:
        # A CTF that is set up is checked even when no calendar session links to it
        heading = f":information_source: CTFtime changed the dates of {ctf}; it has no calendar sessions."
    elif all_overlap:
        heading = (
            f":information_source: CTFtime changed the dates of {ctf}; every calendar session still falls within it."
        )
    else:
        heading = (
            f":warning: CTFtime changed the dates of {ctf}, and not every calendar session falls within it anymore."
        )
    message = (
        f"{heading}\nWas: {period(stored.told_start, stored.told_finish)}\nNow: {period(event.start, event.finish)}"
    )
    if sessions:
        message += f"\n{_sessions(sessions, event)}"
    return DateCheck(message, record)


def _gone(ctftime_id: int, stored: Record | None, sessions: list[Session]) -> DateCheck:
    # Told once, not on every check
    if stored is not None and stored.gone:
        return DateCheck(None, stored)

    if stored is None:
        stored = Record(ctftime_id, title=None, start=None, finish=None, told_start=None, told_finish=None)
    ctf = f"CTFtime event {ctftime_id}" if stored.title is None else _ctf(ctftime_id, stored.title)
    message = f":warning: {ctf} is gone from CTFtime (<https://ctftime.org/event/{ctftime_id}/> is not found)."
    if sessions:
        message += f" Check the calendar sessions linking to it:\n{_sessions(sessions)}"
    return DateCheck(message, replace(stored, gone=True))


def _ctf(ctftime_id: int, title: str) -> str:
    return f"**{_escaped(title)}** (<https://ctftime.org/event/{ctftime_id}/>)"


def _sessions(sessions: list[Session], event: ctftime.Event | None = None) -> str:
    """One line per session, marking the ones outside `event` when it is given."""
    lines = []
    for session in sorted(sessions, key=lambda session: session.start)[:SESSION_LIMIT]:
        mark = "" if event is None or overlaps(session, event) else " :warning: outside the CTF"
        lines.append(f"- {_escaped(session.title)}: {period(session.start, session.end)}{mark}")
    if len(sessions) > SESSION_LIMIT:
        lines.append(f"- and {len(sessions) - SESSION_LIMIT} more")
    return "\n".join(lines)


def _escaped(title: str) -> str:
    return discord.utils.escape_markdown(cut(title, TITLE_LIMIT))


async def check(
    now: datetime,
    alert: Alert,
    also_check: Iterable[int],
    dates_changed: DatesChanged,
    get_event: GetEvent = ctftime.get_event,
) -> CtftimeCheckResult:
    """Check the CTFtime events linked from calendar sessions that haven't ended, plus the ones in `also_check`, and
    post an alert through `alert` when the staff should know. `dates_changed` gets the new dates of every event.

    An event CTFtime can't be asked about is skipped until the next check. An alert that can't be posted is due again
    on the next check.
    """
    # A check that was stopped may still be posting and storing; wait for it, so nothing is posted twice
    await _unfinished.wait()

    result = CtftimeCheckResult()
    for ctftime_id, sessions in _sessions_to_check(now, also_check).items():
        try:
            event = await get_event(ctftime_id)
        except ctftime.CtftimeError as e:
            log.warning(f"CTFtime check skipped CTFtime event {ctftime_id}: {e}")
            result = replace(result, skipped=result.skipped + 1)
            continue

        stored = stored_record(ctftime_id)
        date_check = compare_with_ctftime(ctftime_id, stored, event, sessions)
        # Shielded: when the check is stopped mid-alert, a posted alert is still stored so it is not posted twice
        posted = await _unfinished.finish_even_if_stopped(
            _tell_and_store(stored, date_check, now, alert, dates_changed)
        )
        result = replace(result, checked=result.checked + 1, alerts=result.alerts + posted)
    return result


def _sessions_to_check(now: datetime, also_check: Iterable[int]) -> dict[int, list[Session]]:
    linked = linked_sessions()
    to_check = {
        ctftime_id: sessions
        for ctftime_id, sessions in linked.items()
        if any(session.end > now for session in sessions)
    }
    for ctftime_id in also_check:
        to_check.setdefault(ctftime_id, linked.get(ctftime_id, []))
    return dict(sorted(to_check.items()))


async def _tell_and_store(
    stored: Record | None, date_check: DateCheck, now: datetime, alert: Alert, dates_changed: DatesChanged
) -> bool:
    """Returns whether an alert was posted."""
    record = date_check.record
    posted = False
    if date_check.alert is not None:
        try:
            await alert(record.ctftime_id, date_check.alert)
            posted = True
        except Exception:
            log.exception(f"Could not post the CTFtime check alert: {date_check.alert}")
            # Keep what the staff were told, so the alert is due again
            if stored is None:
                record = replace(record, told_start=None, told_finish=None, gone=False)
            else:
                record = replace(record, told_start=stored.told_start, told_finish=stored.told_finish, gone=stored.gone)
    _store(record, now)
    if record.start is not None and record.finish is not None and not record.gone:
        dates_changed(record.ctftime_id, record.start, record.finish)
    return posted


def stored_record(ctftime_id: int) -> Record | None:
    with db.transaction() as conn:
        row = conn.execute("SELECT * FROM ctftime_events WHERE ctftime_id = ?", (ctftime_id,)).fetchone()
    if row is None:
        return None
    return Record(
        ctftime_id,
        row["title"],
        db.parse_time(row["start"]),
        db.parse_time(row["finish"]),
        db.parse_time(row["told_start"]),
        db.parse_time(row["told_finish"]),
        bool(row["gone"]),
    )


def _store(record: Record, now: datetime) -> None:
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO ctftime_events (ctftime_id, title, start, finish, checked_at, told_start, told_finish, gone) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (ctftime_id) DO UPDATE SET title = excluded.title,"
            " start = excluded.start, finish = excluded.finish, checked_at = excluded.checked_at,"
            " told_start = excluded.told_start, told_finish = excluded.told_finish, gone = excluded.gone",
            (
                record.ctftime_id,
                record.title,
                db.time_text(record.start),
                db.time_text(record.finish),
                db.time_text(now),
                db.time_text(record.told_start),
                db.time_text(record.told_finish),
                int(record.gone),
            ),
        )
