"""Building calendar occurrences and ICS feeds for the calendar tests."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from core import db
from feeds.calendar import store
from feeds.calendar.parse import Occurrence, parse_occurrences
from feeds.calendar.plan import EventDetails, event_title, plan_discord_changes
from tests.factories import utc

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)
WINDOW = timedelta(days=30)
FUTURE = NOW + timedelta(days=7)


def occurrence(
    uid="meeting-1",
    start=utc(2026, 10, 10, 18),
    end=utc(2026, 10, 10, 20),
    title="Weekly meeting",
    description="",
    location="",
    url="",
    slot=None,
):
    return Occurrence(
        uid=uid, start=start, end=end, title=title, description=description, location=location, url=url, slot=slot
    )


def event(
    name="Weekly meeting",
    description="",
    location="See description",
    start=utc(2026, 10, 10, 18),
    end=utc(2026, 10, 10, 20),
):
    """The Discord event the bot has for an occurrence."""
    return EventDetails(name=name, description=description, location=location, start=start, end=end)


def feed(*events):
    """An ICS calendar with these VEVENT bodies."""
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//test//EN"]
    for body in events:
        lines += ["BEGIN:VEVENT", *body.strip().splitlines(), "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return ("\r\n".join(lines) + "\r\n").encode()


def plan(occurrences, known=None, now=NOW, ends=None):
    """ends defaults to every known occurrence ending in the future: it only matters for the ones gone from the feed."""
    known = known or {}
    if ends is None:
        ends = {key: FUTURE for key in known}
    return plan_discord_changes(occurrences, known, ends, now, WINDOW)


def parse(*events, now=NOW, known=()):
    return parse_occurrences(feed(*events), "Europe/Brussels", now, WINDOW, set(known))


def brussels(*args):
    return datetime(*args, tzinfo=ZoneInfo("Europe/Brussels"))


WEEKLY = "UID:series\nDTSTART:20261010T180000Z\nDTEND:20261010T200000Z\nSUMMARY:Weekly meeting\nRRULE:FREQ=WEEKLY"


def store_session(uid, start, end, title, url):
    """A calendar occurrence that the calendar sync created an event for; storing it again is like the next sync."""
    with db.transaction() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO calendar_occurrences (uid, start, discord_event_id, end_time) VALUES (?, '', 1, ?)",
            (uid, db.time_text(end)),
        )
    store.remember_details([Occurrence(uid=uid, start=start, end=end, title=title, url=url)], event_title)
