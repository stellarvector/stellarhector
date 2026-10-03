"""The daily check of the CTFs that calendar sessions link to on CTFtime, telling the admins when their dates change.

decide is pure: it turns what was stored for a CTFtime event and what CTFtime answers now into the alert to post and
what to store. check runs it for every CTF to check, asking CTFtime and posting the alerts.
"""
import logging
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import datetime

import discord

import core.db as db
from utils import ctftime
from utils.text import cut
from utils.unfinished import UnfinishedWork

# How many sessions an alert lists, and how much of a title it shows, to stay well under Discord's 2000 characters
SESSION_LIMIT = 5
TITLE_LIMIT = 100

# The post-and-store work of checks that were stopped while it ran
_unfinished = UnfinishedWork()


@dataclass(frozen=True)
class Session:
    """A calendar occurrence linking to a CTFtime event: the on-campus night, not the whole CTF."""
    title: str
    start: datetime
    end: datetime


@dataclass(frozen=True)
class Record:
    """What is stored for a CTFtime event: its data at the last check, and the start and finish the admins were last
    told about (None until the event was first seen on CTFtime). gone is set once the admins were told CTFtime no
    longer knows the event; title, start and finish are None when it never was seen there."""
    ctftime_id: int
    title: str | None
    start: datetime | None
    finish: datetime | None
    told_start: datetime | None
    told_finish: datetime | None
    gone: bool = False


@dataclass(frozen=True)
class Outcome:
    """The alert to post, None when there is nothing to tell, and the Record to store once it is posted."""
    alert: str | None
    record: Record


@dataclass(frozen=True)
class CheckResult:
    """What one check did: how many CTFs CTFtime answered for, how many alerts were posted, and how many CTFs were
    skipped because CTFtime could not be asked about them."""
    checked: int = 0
    alerts: int = 0
    skipped: int = 0


def decide(ctftime_id, stored, event, sessions):
    """The Outcome of checking the CTFtime event ctftime_id. stored is its Record, None the first time; event is the
    ctftime.Event CTFtime answers now, None when it does not know the event; sessions are the calendar's Sessions
    linking to it."""
    if event is None:
        return _gone(ctftime_id, stored, sessions)

    record = Record(ctftime_id, event.title, event.start, event.finish, told_start=event.start, told_finish=event.finish)
    all_overlap = all(overlaps(session, event) for session in sessions)
    ctf = _ctf(ctftime_id, event.title)

    if stored is None or stored.told_start is None:
        if all_overlap:
            return Outcome(None, record)
        # Probably a typo in the calendar
        return Outcome(f":warning: Not every calendar session of {ctf} falls within the CTF, which runs"
                       f" {_period(event.start, event.finish)} on CTFtime:\n{_sessions(sessions, event)}", record)

    if (stored.told_start, stored.told_finish) == (event.start, event.finish):
        return Outcome(None, record)

    if all_overlap:
        heading = f":information_source: CTFtime changed the dates of {ctf}; every calendar session still falls within it."
    else:
        heading = f":warning: CTFtime changed the dates of {ctf}, and not every calendar session falls within it anymore."
    return Outcome(f"{heading}\nWas: {_period(stored.told_start, stored.told_finish)}\n"
                   f"Now: {_period(event.start, event.finish)}\n{_sessions(sessions, event)}", record)


def reply(result):
    """The /ctftime-check reply after a check."""
    text = (f"CTFtime checked: {_count(result.checked, 'CTF')} checked, {_count(result.alerts, 'alert')} posted.")
    if not result.skipped:
        return f":white_check_mark: {text}"
    return (f":warning: {text} {_count(result.skipped, 'CTF')} {'was' if result.skipped == 1 else 'were'} skipped"
            f" because CTFtime could not be reached; they are tried again on the next check.")


def _count(number, noun):
    return f"{number} {noun}" if number == 1 else f"{number} {noun}s"


def _gone(ctftime_id, stored, sessions):
    """The Outcome when CTFtime does not know the event: told once, not on every check."""
    if stored is not None and stored.gone:
        return Outcome(None, stored)

    if stored is None:
        stored = Record(ctftime_id, title=None, start=None, finish=None, told_start=None, told_finish=None)
    ctf = f"CTFtime event {ctftime_id}" if stored.title is None else _ctf(ctftime_id, stored.title)
    return Outcome(f":warning: {ctf} is gone from CTFtime (<https://ctftime.org/event/{ctftime_id}/> is not found)."
                   f" Check the calendar sessions linking to it:\n{_sessions(sessions)}", replace(stored, gone=True))


def _ctf(ctftime_id, title):
    """The CTF's name, linking to CTFtime without a preview."""
    return f"**{_escaped(title)}** (<https://ctftime.org/event/{ctftime_id}/>)"


def _sessions(sessions, event=None):
    """One line per session, marking the ones outside the window of event when it is given."""
    lines = []
    for session in sorted(sessions, key=lambda session: session.start)[:SESSION_LIMIT]:
        mark = "" if event is None or overlaps(session, event) else " :warning: outside the CTF"
        lines.append(f"- {_escaped(session.title)}: {_period(session.start, session.end)}{mark}")
    if len(sessions) > SESSION_LIMIT:
        lines.append(f"- and {len(sessions) - SESSION_LIMIT} more")
    return "\n".join(lines)


def _period(start, end):
    return f"{_timestamp(start)} to {_timestamp(end)}"


def _timestamp(moment):
    return f"<t:{int(moment.timestamp())}:F>"


def _escaped(title):
    """title cut to TITLE_LIMIT, with its markdown escaped so it shows as typed."""
    return discord.utils.escape_markdown(cut(title, TITLE_LIMIT))


async def check(now, alert, get_event=ctftime.get_event):
    """Check every CTFtime event linked from a calendar session that is not over at now, and post an alert through
    alert(ctftime_id, message) when the admins should know. Returns a CheckResult.

    An event CTFtime can't be asked about is logged and skipped until the next check. An alert that can't be posted
    is logged; CTFtime's data is stored, but the alert is due again on the next check.
    """
    # A check that was stopped may still be posting and storing; wait for it, so it is not posted again
    await _unfinished.wait()

    result = CheckResult()
    for ctftime_id, sessions in _sessions_to_check(now).items():
        try:
            event = await get_event(ctftime_id)
        except ctftime.CtftimeError as e:
            logging.getLogger("bot").warning(f"CTFtime check skipped CTFtime event {ctftime_id}: {e}")
            result = replace(result, skipped=result.skipped + 1)
            continue

        stored = _stored(ctftime_id)
        outcome = decide(ctftime_id, stored, event, sessions)
        # Shielded: when the check is stopped mid-alert, a posted alert is still remembered so it is not posted twice
        posted = await _unfinished.finish_even_if_stopped(_tell_and_store(stored, outcome, now, alert))
        result = replace(result, checked=result.checked + 1, alerts=result.alerts + posted)
    return result


def linked_sessions():
    """The calendar's Sessions per CTFtime event they link to, sorted by start. Only the occurrences the calendar sync
    has an event for are known, so sessions further away than its lookahead are not in here yet."""
    sessions = defaultdict(list)
    with db.transaction() as conn:
        rows = conn.execute("SELECT ctftime_id, title, start_time, end_time FROM calendar_occurrences "
                            "WHERE ctftime_id IS NOT NULL AND start_time IS NOT NULL ORDER BY start_time").fetchall()
    for row in rows:
        sessions[row["ctftime_id"]].append(Session(row["title"], db.parse_time(row["start_time"]),
                                                   db.parse_time(row["end_time"])))
    return dict(sorted(sessions.items()))


def overlaps(session, event):
    """Whether session falls (partly) within the CTF event."""
    return session.start < event.finish and session.end > event.start


def _sessions_to_check(now):
    """The Sessions per CTFtime event to check: the ones linked from a calendar session that is not over."""
    # TODO ctf-lifecycle: also check the CTFs that are set up and not locked yet, even without a session
    return {ctftime_id: linked for ctftime_id, linked in linked_sessions().items()
            if any(session.end > now for session in linked)}


async def _tell_and_store(stored, outcome, now, alert):
    """Post the outcome's alert, if any, and store its record. stored is the Record the outcome was decided from.
    Returns whether an alert was posted."""
    record = outcome.record
    posted = False
    if outcome.alert is not None:
        try:
            await alert(record.ctftime_id, outcome.alert)
            posted = True
        except Exception:
            logging.getLogger("bot").exception(f"Could not post the CTFtime check alert: {outcome.alert}")
            # What the admins were told stays as it was, so the alert is due again
            if stored is None:
                record = replace(record, told_start=None, told_finish=None, gone=False)
            else:
                record = replace(record, told_start=stored.told_start, told_finish=stored.told_finish, gone=stored.gone)
    _store(record, now)
    return posted


def _stored(ctftime_id):
    with db.transaction() as conn:
        row = conn.execute("SELECT * FROM ctftime_events WHERE ctftime_id = ?", (ctftime_id,)).fetchone()
    if row is None:
        return None
    return Record(ctftime_id, row["title"], db.parse_time(row["start"]), db.parse_time(row["finish"]),
                  db.parse_time(row["told_start"]), db.parse_time(row["told_finish"]), bool(row["gone"]))


def _store(record, now):
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO ctftime_events (ctftime_id, title, start, finish, checked_at, told_start, told_finish, gone) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (ctftime_id) DO UPDATE SET title = excluded.title,"
            " start = excluded.start, finish = excluded.finish, checked_at = excluded.checked_at,"
            " told_start = excluded.told_start, told_finish = excluded.told_finish, gone = excluded.gone",
            (record.ctftime_id, record.title, db.time_text(record.start), db.time_text(record.finish),
             db.time_text(now), db.time_text(record.told_start), db.time_text(record.told_finish), int(record.gone)))
