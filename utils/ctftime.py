import asyncio
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import aiohttp

API_URL = "https://ctftime.org/api/v1"

# CTFtime filters on an event's finish, not its start, so ask this much further
# to also get the events that start in the range but finish after it
FINISH_MARGIN = timedelta(days=30)

# CTFtime does not cap limit, but smaller pages keep each response small
PAGE_SIZE = 100

# CTFtime refuses some non-browser User-Agents (curl's and requests' are blocked)
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"
TIMEOUT = aiohttp.ClientTimeout(total=30)

_EVENT_LINK = re.compile(r"ctftime\.org/event/(\d+)")


class CtftimeError(Exception):
    """CTFtime could not be reached or answered with an error (other than not found)."""


@dataclass(frozen=True)
class Event:
    id: int
    title: str
    start: datetime
    finish: datetime
    format: str
    weight: float
    onsite: bool
    url: str
    ctftime_url: str


async def fetch_json(url, params=None):
    """The JSON CTFtime answers for url, or None on a 404."""
    try:
        async with aiohttp.ClientSession(headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT) as session:
            async with session.get(url, params=params) as response:
                if response.status == 404:
                    return None
                response.raise_for_status()
                return await response.json()
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
        raise CtftimeError(f"CTFtime request to {url} failed: {e!r}") from e


async def get_event(event_id, fetch=fetch_json):
    """The event with this id, or None when CTFtime does not know it."""
    data = await fetch(f"{API_URL}/events/{event_id}/")
    if data is None:
        return None
    return _parse_event(data)


async def list_events(start, finish, fetch=fetch_json):
    """Every event starting from start until (not including) finish, both aware datetimes.

    Events running longer than FINISH_MARGIN past finish are not returned by CTFtime, so they are missed.
    """
    # CTFtime ignores offset but sorts by start, so the next page is asked from the latest start seen
    # so far. Events with that start come back again and are skipped by id.
    events = {}
    page_start = int(start.timestamp())
    while True:
        page = await fetch(f"{API_URL}/events/", {
            "limit": PAGE_SIZE,
            "start": page_start,
            "finish": int((finish + FINISH_MARGIN).timestamp()),
        })
        if not isinstance(page, list):
            raise CtftimeError(f"CTFtime answered an event list request with {page!r}")
        page = [_parse_event(data) for data in page]
        for event in page:
            events.setdefault(event.id, event)

        latest_start = max((event.start for event in page), default=finish)
        if len(page) < PAGE_SIZE or latest_start >= finish:
            break
        # A full page that all starts at the same second would be asked again forever; skipping past
        # that second could only lose events if more than PAGE_SIZE of them start at once
        page_start = max(int(latest_start.timestamp()), page_start + 1)

    return [event for event in events.values() if start <= event.start < finish]


def parse_ctftime_id(text):
    """The event id from the first ctftime.org/event/<id> link in text, or None."""
    match = _EVENT_LINK.search(text)
    return int(match.group(1)) if match else None


def _parse_event(data):
    try:
        return Event(
            id=data["id"],
            title=data["title"],
            start=_parse_time(data["start"]),
            finish=_parse_time(data["finish"]),
            format=data["format"],
            weight=float(data["weight"]),
            onsite=bool(data["onsite"]),
            url=data["url"],
            ctftime_url=data["ctftime_url"],
        )
    except (KeyError, TypeError, ValueError) as e:
        raise CtftimeError(f"Unexpected CTFtime event data {data!r}") from e


def _parse_time(value):
    return datetime.fromisoformat(value).astimezone(timezone.utc)
