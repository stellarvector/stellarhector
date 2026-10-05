"""The CTFtime API: looking up an event by its id and listing the events in a date range."""

import re
from collections.abc import Awaitable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, cast

import aiohttp

API_URL = "https://ctftime.org/api/v1"

# CTFtime filters on an event's finish, not its start, so the bot asks this much further to also get the events that
# start in the range but finish after it. Results are sorted by start and paging stops at the range's finish, so a wide
# margin costs nothing extra.
FINISH_MARGIN = timedelta(days=365)

# CTFtime does not cap the page size, but smaller pages keep each response small
PAGE_SIZE = 100

# CTFtime refuses some non-browser User-Agents (curl's and requests' are blocked)
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"
TIMEOUT = aiohttp.ClientTimeout(total=30)

_EVENT_LINK = re.compile(r"ctftime\.org/event/(\d+)", re.IGNORECASE)


class CtftimeError(Exception):
    """CTFtime could not be reached, or it answered with an error other than 404."""


class Fetch(Protocol):
    def __call__(self, url: str, params: dict[str, int] | None = None, /) -> Awaitable[object]: ...


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


async def fetch_json(url: str, params: dict[str, int] | None = None) -> object:
    """Returns None on a 404."""
    try:
        async with aiohttp.ClientSession(headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT) as session:
            async with session.get(url, params=params) as response:
                if response.status == 404:
                    return None
                response.raise_for_status()
                return await response.json()
    except (TimeoutError, aiohttp.ClientError, ValueError) as e:
        raise CtftimeError(f"CTFtime request to {url} failed: {e!r}") from e


async def get_event(event_id: int, fetch: Fetch = fetch_json) -> Event | None:
    data = await fetch(f"{API_URL}/events/{event_id}/")
    if data is None:
        return None
    return _parse_event(data)


async def list_events(start: datetime, finish: datetime, fetch: Fetch = fetch_json) -> list[Event]:
    """Every event starting in [`start`, `finish`). Events that run longer than FINISH_MARGIN past `finish` are missed,
    as CTFtime does not return them."""
    # CTFtime ignores the offset but sorts by start, so the next page is asked from the latest start seen so far.
    # Events with that start come back again and are skipped by id.
    events: dict[int, Event] = {}
    page_start = int(start.timestamp())
    while True:
        page = await fetch(
            f"{API_URL}/events/",
            {
                "limit": PAGE_SIZE,
                "start": page_start,
                "finish": int((finish + FINISH_MARGIN).timestamp()),
            },
        )
        if not isinstance(page, list):
            raise CtftimeError(f"CTFtime answered an event list request with {page!r}")
        parsed = [_parse_event(data) for data in page]
        for event in parsed:
            events.setdefault(event.id, event)

        latest_start = max((event.start for event in parsed), default=finish)
        if len(parsed) < PAGE_SIZE or latest_start >= finish:
            break
        # A full page of events that all start in the same second would be asked again forever. Skipping past that
        # second only loses events when more than PAGE_SIZE of them start at once.
        page_start = max(int(latest_start.timestamp()), page_start + 1)

    return [event for event in events.values() if start <= event.start < finish]


def parse_ctftime_id(text: str) -> int | None:
    """The event id in the first ctftime.org/event/<id> link in `text`."""
    match = _EVENT_LINK.search(text)
    return int(match.group(1)) if match else None


def _parse_event(data: object) -> Event:
    # Anything else than the expected JSON object fails with one of the caught errors
    fields = cast(dict[str, Any], data)
    try:
        return Event(
            id=fields["id"],
            title=fields["title"],
            start=_parse_time(fields["start"]),
            finish=_parse_time(fields["finish"]),
            format=fields["format"],
            weight=float(fields["weight"]),
            onsite=bool(fields["onsite"]),
            url=fields["url"],
            ctftime_url=fields["ctftime_url"],
        )
    except (KeyError, TypeError, ValueError) as e:
        raise CtftimeError(f"Unexpected CTFtime event data {data!r}") from e


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)
