"""The table of upcoming CTFs from CTFtime that is posted in #ctf-selection.

Everything except `post_table` is pure, so /ctftime-table and the monthly job build the same lines.
"""

import calendar
import re
from collections.abc import Awaitable, Callable, Iterable
from datetime import date, datetime
from zoneinfo import ZoneInfo

import discord

from feeds import ctftime
from feeds.calendar.sessions import Session, linked_sessions, overlaps
from utils.text import cut

# Discord refuses messages longer than this
MESSAGE_LIMIT = 2000

NAME_WIDTH = 20
FORMAT_WIDTH = 8
# CTFtime's format names, shortened to fit FORMAT_WIDTH
FORMAT_NAMES = {
    "Attack-Defense": "A/D",
    "Hack quest": "Quest",
}

# The CTF has a session in the calendar
IN_CALENDAR = "✅"
# The CTF has a session in the calendar, but at least one session no longer overlaps the CTF
NOT_OVERLAPPING = "⚠️"
# An online Jeopardy CTF that counts for the CTFtime rating: the kind the team plays most
RECOMMENDED = "⭐"

# Not %a: weekday names must not depend on the server's locale
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

NO_EVENTS = "_No CTFs on CTFtime._"

_INVALID_MONTH = "{!r} is not a month, use a month number (11) or YYYY-MM (2026-11)"

_MONTH_ARGUMENT = re.compile(r"^(?:(\d{4})-)?(\d{1,2})$")

YearMonth = tuple[int, int]
ListEvents = Callable[[datetime, datetime], Awaitable[list[ctftime.Event]]]
LinkedSessions = Callable[[], dict[int, list[Session]]]


def parse_start_month(value: str | None, today: date) -> YearMonth:
    """The current month when `value` is None, else the month `value` gives as YYYY-MM or as a month number. A month
    number means the next time that month comes around, the current month included. Raises ValueError for anything
    else."""
    if value is None:
        return today.year, today.month

    match = _MONTH_ARGUMENT.match(value.strip())
    if not match or not 1 <= int(match.group(2)) <= 12:
        raise ValueError(_INVALID_MONTH.format(value))
    year, month = match.group(1), int(match.group(2))

    if year is not None:
        # The month after the last listed one must still be a valid datetime, for up to 12 months
        if not datetime.min.year <= int(year) <= datetime.max.year - 1:
            raise ValueError(_INVALID_MONTH.format(value))
        return int(year), month
    return (today.year if month >= today.month else today.year + 1), month


def months(start: YearMonth, count: int) -> list[YearMonth]:
    return [_add_months(start, i) for i in range(count)]


def date_range(month_list: list[YearMonth], tz: str) -> tuple[datetime, datetime]:
    """The aware datetimes [start, finish) covering the consecutive months in `month_list`."""
    zone = ZoneInfo(tz)
    first_year, first_month = month_list[0]
    end_year, end_month = _add_months(month_list[-1], 1)
    return datetime(first_year, first_month, 1, tzinfo=zone), datetime(end_year, end_month, 1, tzinfo=zone)


def mark(event: ctftime.Event, sessions: list[Session] | None) -> str | None:
    if not sessions:
        return None
    if all(overlaps(session, event) for session in sessions):
        return IN_CALENDAR
    return NOT_OVERLAPPING


def is_recommended(event: ctftime.Event) -> bool:
    return not event.onsite and event.weight > 0 and event.format == "Jeopardy"


def format_line(event: ctftime.Event, tz: str, event_mark: str | None = None) -> str:
    """The fixed-width columns in inline code, then the mark, the CTFtime link without a preview, and a star for a
    recommended CTF."""
    zone = ZoneInfo(tz)
    columns = "  ".join(
        [
            f"{_moment(event.start, zone)} -> {_moment(event.finish, zone)}",
            _cut(event.title, NAME_WIDTH),
            _cut(FORMAT_NAMES.get(event.format, event.format), FORMAT_WIDTH),
            f"{event.weight:5.1f}",
            "onsite" if event.onsite else "online",
        ]
    )
    mark_part = f" {event_mark}" if event_mark else ""
    star = f" {RECOMMENDED}" if is_recommended(event) else ""
    return f"`{columns}`{mark_part} [ctftime](<{event.ctftime_url}>){star}"


def table_lines(
    events: Iterable[ctftime.Event],
    month_list: list[YearMonth],
    tz: str,
    marks: dict[int, str | None] | None = None,
) -> list[str]:
    """A header per month, the first marked to validate and the others as a preview, followed by its events sorted by
    start. `marks` maps an event id to its mark."""
    zone = ZoneInfo(tz)
    marks = marks or {}

    by_month: dict[YearMonth, list[ctftime.Event]] = {month: [] for month in month_list}
    for event in events:
        start = event.start.astimezone(zone)
        by_month.get((start.year, start.month), []).append(event)

    lines: list[str] = []
    for index, (year, month) in enumerate(month_list):
        if lines:
            lines.append("")
        lines.append(_header(year, month, "validate" if index == 0 else "preview"))
        month_events = sorted(by_month[(year, month)], key=lambda event: (event.start, event.id))
        lines.extend(format_line(event, tz, marks.get(event.id)) for event in month_events)
        if not month_events:
            lines.append(NO_EVENTS)
    return lines


def split_messages(lines: list[str], limit: int = MESSAGE_LIMIT) -> list[str]:
    """Joins `lines` into as few messages of at most `limit` characters as possible, splitting only between lines.

    Blank lines at the start or end of a message are dropped, and a month header never ends a message when its CTFs
    follow in the next one.
    """
    messages: list[str] = []
    current: list[str] = []
    length = 0

    def flush() -> None:
        while current and not current[-1]:
            current.pop()
        if current:
            messages.append("\n".join(current))

    for line in lines:
        if not current and not line:
            continue
        added = len(line) + (1 if current else 0)
        if current and length + added > limit:
            carried = [current.pop()] if len(current) > 1 and _is_header(current[-1]) else []
            flush()
            current = carried + ([line] if line else [])
            length = len("\n".join(current))
        else:
            current.append(line)
            length += added
    flush()
    return messages


async def post_table(
    channel: discord.abc.Messageable,
    start: YearMonth,
    count: int,
    tz: str,
    hide_finished_at: datetime | None = None,
    list_events: ListEvents = ctftime.list_events,
    linked_sessions: LinkedSessions = linked_sessions,
) -> int:
    """Post the table for `count` months from `start`, marking the CTFs that have sessions in the calendar. With
    `hide_finished_at`, CTFs that finished before that moment are left out. Returns how many CTFs it lists.

    Raises CtftimeError before anything is posted when CTFtime can't be reached. A discord.HTTPException may come
    after some messages are already posted.
    """
    month_list = months(start, count)
    events = await list_events(*date_range(month_list, tz))
    if hide_finished_at is not None:
        events = [event for event in events if event.finish >= hide_finished_at]
    sessions = linked_sessions()
    marks = {event.id: mark(event, sessions.get(event.id)) for event in events}

    for message in split_messages(table_lines(events, month_list, tz, marks)):
        # A CTF name must never ping anyone
        await channel.send(message, allowed_mentions=discord.AllowedMentions.none())
    return len(events)


def _moment(moment: datetime, zone: ZoneInfo) -> str:
    """Like "Fri 09/10 18:00", in `zone`."""
    local = moment.astimezone(zone)
    return f"{WEEKDAYS[local.weekday()]} {local:%d/%m %H:%M}"


def _header(year: int, month: int, label: str) -> str:
    return f"**{calendar.month_name[month]} {year}** ({label})"


def _is_header(line: str) -> bool:
    return line.startswith("**")


def _add_months(year_month: YearMonth, count: int) -> YearMonth:
    year, month = year_month
    index = year * 12 + month - 1 + count
    return index // 12, index % 12 + 1


def _cut(text: str, width: int) -> str:
    """`text` on one line without backticks, cut to `width` with … and padded to exactly `width`."""
    return cut(" ".join(text.replace("`", "'").split()), width).ljust(width)
