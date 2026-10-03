"""The list of upcoming CTFs from CTFtime that is posted in #ctf-selection.

Everything except post_table is pure, so /ctftime-table and the monthly job share the same lines.
"""
import calendar
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import discord

from utils import ctftime, ctftime_check
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
# The CTF has a session in the calendar, but a session no longer overlaps the CTF
NOT_OVERLAPPING = "⚠️"

NO_EVENTS = "_No CTFs on CTFtime._"

_INVALID_MONTH = "{!r} is not a month, use a month number (11) or YYYY-MM (2026-11)"

_MONTH_ARGUMENT = re.compile(r"^(?:(\d{4})-)?(\d{1,2})$")


def parse_start_month(value, today):
    """The (year, month) to start from: next month when value is empty, else YYYY-MM or a month number.

    A month number means the first time that month comes around, this month included.
    Raises ValueError for anything else.
    """
    if value is None:
        return _add_months((today.year, today.month), 1)

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


def months(start, count):
    """count (year, month) pairs from start on."""
    return [_add_months(start, i) for i in range(count)]


def date_range(month_list, tz):
    """The aware datetimes [start, finish) covering the consecutive months in month_list in timezone tz."""
    zone = ZoneInfo(tz)
    first_year, first_month = month_list[0]
    end_year, end_month = _add_months(month_list[-1], 1)
    return datetime(first_year, first_month, 1, tzinfo=zone), datetime(end_year, end_month, 1, tzinfo=zone)


def mark(event, sessions):
    """IN_CALENDAR, NOT_OVERLAPPING or None for an event with these calendar ctftime_check.Sessions."""
    if not sessions:
        return None
    if all(ctftime_check.overlaps(session, event) for session in sessions):
        return IN_CALENDAR
    return NOT_OVERLAPPING


def format_line(event, tz, event_mark=None):
    """One CTF: the fixed-width columns in inline code, then the mark if any and the CTFtime link without preview."""
    zone = ZoneInfo(tz)
    # A CTF finishing at midnight is over the day before
    last_moment = max(event.start, event.finish - timedelta(seconds=1))
    columns = "  ".join([
        f"{event.start.astimezone(zone):%m-%d} → {last_moment.astimezone(zone):%m-%d}",
        _cut(event.title, NAME_WIDTH),
        _cut(FORMAT_NAMES.get(event.format, event.format), FORMAT_WIDTH),
        f"{event.weight:5.1f}",
        "onsite" if event.onsite else "online",
    ])
    mark_part = f" {event_mark}" if event_mark else ""
    return f"`{columns}`{mark_part} [ctftime](<{event.ctftime_url}>)"


def table_lines(events, month_list, tz, marks=None):
    """The lines for every month in month_list: a header per month (the first to validate, the others a preview)
    and its events sorted by start. marks maps an event id to its mark."""
    zone = ZoneInfo(tz)
    marks = marks or {}

    by_month = {month: [] for month in month_list}
    for event in events:
        start = event.start.astimezone(zone)
        by_month.get((start.year, start.month), []).append(event)

    lines = []
    for index, (year, month) in enumerate(month_list):
        if lines:
            lines.append("")
        lines.append(_header(year, month, "validate" if index == 0 else "preview"))
        month_events = sorted(by_month[(year, month)], key=lambda event: (event.start, event.id))
        lines.extend(format_line(event, tz, marks.get(event.id)) for event in month_events)
        if not month_events:
            lines.append(NO_EVENTS)
    return lines


def split_messages(lines, limit=MESSAGE_LIMIT):
    """lines joined into as few messages of at most limit characters as possible, only split between lines.

    Blank lines at the start or end of a message are dropped, and a month header is never the last line of
    a message when its CTFs follow in the next one.
    """
    messages = []
    current = []
    length = 0

    def flush():
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


async def post_table(channel, start, count, tz, list_events=ctftime.list_events,
                     linked_sessions=ctftime_check.linked_sessions):
    """Post the table for count months from start, as (year, month), in channel, marking the CTFs with sessions in
    the calendar. Returns how many CTFs it lists.

    Raises CtftimeError, before anything is posted, when CTFtime can't be reached.
    A discord.HTTPException may come after some messages are already posted.
    """
    month_list = months(start, count)
    events = await list_events(*date_range(month_list, tz))
    sessions = linked_sessions()
    marks = {event.id: mark(event, sessions.get(event.id)) for event in events}

    for message in split_messages(table_lines(events, month_list, tz, marks)):
        # A CTF name must never ping anyone
        await channel.send(message, allowed_mentions=discord.AllowedMentions.none())
    return len(events)


def _header(year, month, label):
    return f"**{calendar.month_name[month]} {year}** ({label})"


def _is_header(line):
    return line.startswith("**")


def _add_months(year_month, count):
    year, month = year_month
    index = year * 12 + month - 1 + count
    return index // 12, index % 12 + 1


def _cut(text, width):
    """text on one line without backticks, cut to width with … and padded to exactly width."""
    return cut(" ".join(text.replace("`", "'").split()), width).ljust(width)
