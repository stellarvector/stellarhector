"""Reading the ICS calendar feed into occurrences: recurring events are expanded, times are made aware, and cancelled
occurrences are left out."""

import logging
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import NamedTuple
from zoneinfo import ZoneInfo

import icalendar
import recurring_ical_events
import x_wr_timezone
from icalendar.cal import Component

from core import db
from feeds import FeedError
from feeds.ctftime import parse_ctftime_id

log = logging.getLogger("bot")


# All-day events run from midnight to this time on their last day
END_OF_DAY = time(23, 59)


# The expansion reads dates and floating times in its own timezone, so it gets this much extra on both sides of the
# window; the plan makes the exact cut
EXPANSION_MARGIN = timedelta(days=1)


class OccurrenceKey(NamedTuple):
    """Identifies an occurrence across syncs, and its row in calendar_occurrences."""

    uid: str
    # The slot as db.time_text, or empty for an event that does not recur
    slot: str


class EmptyFeed(FeedError):
    """The calendar feed has no events while the bot manages some. A hiccup of the calendar provider is more likely
    than every event being cancelled at once."""


@dataclass(frozen=True)
class Occurrence:
    """One occurrence of a calendar event, with an aware start and end.

    `slot` is the start the occurrence has in its recurring series (its RECURRENCE-ID), which differs from `start` when
    the occurrence was moved. It is None for an event that does not recur.
    """

    uid: str
    start: datetime
    end: datetime
    title: str
    description: str = ""
    location: str = ""
    url: str = ""
    slot: datetime | None = None

    @property
    def key(self) -> OccurrenceKey:
        """The UID and the slot, so moving an occurrence keeps its key."""
        return OccurrenceKey(self.uid, "" if self.slot is None else _utc_text(self.slot))

    @property
    def ctftime_id(self) -> int | None:
        """The CTFtime event this occurrence is a CTF session of: the one linked in the URL, else the one linked in
        the description. None for a regular event, such as a meetup."""
        ctftime_id = parse_ctftime_id(self.url)
        return parse_ctftime_id(self.description) if ctftime_id is None else ctftime_id


def parse_occurrences(
    ics: bytes, tz: str, now: datetime, lookahead: timedelta, known: Collection[OccurrenceKey] = frozenset()
) -> list[Occurrence]:
    """The occurrences in the `ics` feed that are running at `now` or start within `lookahead` of it, give or take a
    day; the plan makes the exact cut. Recurring events are expanded into their occurrences. Times without a timezone
    are read in `tz`, and all-day events run from 00:00 on their first day to 23:59 on their last day in `tz`.

    The occurrences with a key in `known` are included wherever they moved to, as long as they are still in the feed.

    Events without a UID or an end, events with properties that can't be read, and cancelled occurrences are left
    out. Raises FeedError when `ics` is not an ICS calendar, and EmptyFeed when it has no usable events while `known`
    is not empty.
    """
    try:
        calendar = icalendar.Calendar.from_ical(ics)
    except ValueError as e:
        raise FeedError(f"Calendar feed is not a valid ICS calendar: {e}") from e

    # Unusable events are dropped before expanding, so the expansion only sees events it can read
    calendar.subcomponents = [
        component for component in calendar.subcomponents if component.name != "VEVENT" or _is_usable(component)
    ]
    # The expansion reads floating times in X-WR-TIMEZONE. Converting them once here makes _find read them in that
    # zone too.
    calendar = _standard(calendar)
    if known and not calendar.walk("VEVENT"):
        raise EmptyFeed(
            f"Calendar feed has no events while the bot manages {len(known)}, skipped to not cancel them all"
        )

    # The expansion drops RRULE and RDATE, so whether an occurrence belongs to a series is determined beforehand
    recurring = {
        _uid(component)
        for component in calendar.walk("VEVENT")
        if any(name in component for name in ("RRULE", "RDATE", "RECURRENCE-ID"))
    }

    zone = ZoneInfo(tz)
    expanded = _expand(calendar, (now - EXPANSION_MARGIN, now + lookahead + EXPANSION_MARGIN))

    occurrences = _occurrences(expanded, zone, recurring)
    moved_away = set(known) - {occurrence.key for occurrence in occurrences}
    return occurrences + [occurrence for key in moved_away for occurrence in _find(calendar, key, zone, recurring)]


def _occurrences(expanded: Iterable[Component], zone: ZoneInfo, recurring: set[str]) -> list[Occurrence]:
    # Cancelled occurrences, including single ones in a series, are left out as if they were not in the feed
    return [
        _occurrence(event, zone, recurring) for event in expanded if str(event.get("STATUS", "")).upper() != "CANCELLED"
    ]


def _find(calendar: icalendar.Calendar, key: OccurrenceKey, zone: ZoneInfo, recurring: set[str]) -> list[Occurrence]:
    """The occurrence with `key` wherever it is in time, in a list that is empty when it is not in the calendar.

    A known occurrence outside the window is a moved one-off event, a moved override in a series (RECURRENCE-ID), or
    an occurrence that a series' rule generates at its slot and that was in the window when the window was longer.
    """
    uid, slot = key
    events = [component for component in calendar.walk("VEVENT") if _uid(component) == uid]
    if uid not in recurring and slot:
        return []
    overrides = [
        event
        for event in events
        if "RECURRENCE-ID" in event and db.time_text(_slot(event.decoded("RECURRENCE-ID"), zone)) == slot
    ]

    # The event on its own, with the calendar's timezones, so expanding it gives only its occurrences
    alone = icalendar.Calendar(calendar)
    others = [component for component in calendar.subcomponents if component.name != "VEVENT"]
    if uid not in recurring or overrides:
        alone.subcomponents = others + (overrides or events)
        window = None
    else:
        # The rule may go on forever, so the series is only expanded around the slot
        alone.subcomponents = others + events
        start = db.parse_time(slot)
        window = (start - EXPANSION_MARGIN, start + EXPANSION_MARGIN)
    return [occurrence for occurrence in _occurrences(_expand(alone, window), zone, recurring) if occurrence.key == key]


def _standard(calendar: icalendar.Calendar) -> icalendar.Calendar:
    """Converts floating times to the calendar's X-WR-TIMEZONE, when it has one."""
    try:
        return x_wr_timezone.to_standard(calendar)
    except (KeyError, ValueError) as e:
        raise FeedError(f"Calendar feed has an unknown X-WR-TIMEZONE: {e!r}") from e


def _expand(calendar: icalendar.Calendar, window: tuple[datetime, datetime] | None = None) -> list[Component]:
    """The occurrences of the calendar's events, as events, between the (start, end) of `window`, or all of them when
    `window` is None."""
    try:
        query = recurring_ical_events.of(calendar)
        return query.all() if window is None else query.between(*window)
    except (recurring_ical_events.InvalidCalendar, ValueError) as e:
        raise FeedError(f"Calendar feed could not be expanded: {e!r}") from e


def _uid(event: Component) -> str:
    return str(event["UID"]).strip()


def _is_usable(event: Component) -> bool:
    """Logs why the event is skipped when it is not usable."""
    uid = str(event.get("UID", "")).strip()
    summary = str(event.get("SUMMARY", ""))
    if not uid:
        log.warning(f"Calendar event {summary!r} has no UID, skipped")
        return False
    if event.errors:
        # icalendar does not fail on values it can't read, but leaves them as plain text
        log.warning(f"Calendar event {uid} ({summary!r}) has unreadable properties {event.errors}, skipped")
        return False
    if "DTSTART" not in event:
        log.warning(f"Calendar event {uid} ({summary!r}) has no start, skipped")
        return False

    start = event.decoded("DTSTART")
    if "DTEND" in event:
        # A timed start with an all-day end, or the other way around, is not a valid period
        if isinstance(event.decoded("DTEND"), datetime) != isinstance(start, datetime):
            log.warning(f"Calendar event {uid} ({summary!r}) mixes a date and a time, skipped")
            return False
        return True
    # An all-day event without an end lasts one day, but a timed one has no end the bot can use
    if "DURATION" not in event and isinstance(start, datetime):
        log.warning(f"Calendar event {uid} ({summary!r}) has no end, skipped")
        return False
    return True


def _occurrence(event: Component, zone: ZoneInfo, recurring: set[str]) -> Occurrence:
    # An expanded event always has DTSTART, DTEND and RECURRENCE-ID
    start = event.decoded("DTSTART")
    end = event.decoded("DTEND")
    if isinstance(start, datetime):
        start, end = _to_utc(start, zone), _to_utc(end, zone)
    else:
        # The ICS end of an all-day event is the day after its last day
        start, end = _start_of_day(start, zone), _end_of_day(end - timedelta(days=1), zone)
    uid = _uid(event)

    return Occurrence(
        uid=uid,
        start=start,
        end=end,
        title=str(event.get("SUMMARY", "")),
        description=str(event.get("DESCRIPTION", "")),
        location=str(event.get("LOCATION", "")),
        url=str(event.get("URL", "")),
        slot=_slot(event.decoded("RECURRENCE-ID"), zone) if uid in recurring else None,
    )


def _slot(recurrence_id: date | datetime, zone: ZoneInfo) -> datetime:
    if isinstance(recurrence_id, datetime):
        return _to_utc(recurrence_id, zone)
    return _start_of_day(recurrence_id, zone)


def _to_utc(moment: datetime, zone: ZoneInfo) -> datetime:
    """Reads a floating time as one in `zone`."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=zone)
    return moment.astimezone(UTC)


def _start_of_day(day: date, zone: ZoneInfo) -> datetime:
    return datetime.combine(day, time(), zone)


def _end_of_day(day: date, zone: ZoneInfo) -> datetime:
    return datetime.combine(day, END_OF_DAY, zone)


def _utc_text(moment: datetime) -> str:
    # db.time_text, for a moment that is never None
    return moment.astimezone(UTC).isoformat()
