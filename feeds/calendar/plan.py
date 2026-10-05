"""Planning which Discord events to create, update, recreate, cancel or forget so they match the calendar."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from feeds.calendar.parse import Occurrence, OccurrenceKey
from utils.text import cut

# Discord refuses events that a bot creates with a start in the past, so running events start this much from now
START_DELAY = timedelta(minutes=1)

# Discord's limits for a scheduled event
NAME_LIMIT = 100
DESCRIPTION_LIMIT = 1000
LOCATION_LIMIT = 100

NO_LOCATION = "See description"
NO_TITLE = "Untitled event"


@dataclass(frozen=True)
class EventDetails:
    name: str
    description: str
    location: str
    start: datetime
    end: datetime


@dataclass(frozen=True)
class Create:
    occurrence: Occurrence
    details: EventDetails


@dataclass(frozen=True)
class Update:
    occurrence: Occurrence
    details: EventDetails


@dataclass(frozen=True)
class Recreate:
    """Create the Discord event again, deleting the one Discord still has. Either the event was deleted in Discord, or
    it is running there while the calendar moved it to later, and Discord won't move the start of a running event."""

    occurrence: Occurrence
    details: EventDetails


@dataclass(frozen=True)
class Cancel:
    """Delete the Discord event and reply to its announcement, as the occurrence is gone from the calendar or
    cancelled there."""

    key: OccurrenceKey


@dataclass(frozen=True)
class Prune:
    """Forget the occurrence, which is over, and delete its Discord event if that still exists."""

    key: OccurrenceKey


Action = Create | Update | Recreate | Cancel | Prune


def plan_discord_changes(
    occurrences: Iterable[Occurrence],
    known: Mapping[OccurrenceKey, EventDetails | None],
    ends: Mapping[OccurrenceKey, datetime],
    now: datetime,
    lookahead: timedelta,
) -> list[Action]:
    """The actions that bring Discord in line with the feed. `known` maps the key of each occurrence the bot already
    created an event for to the details that event currently has in Discord, or to None when the event is gone from
    Discord. `ends` maps the same keys to the end each occurrence had in the calendar at the last sync.

    New occurrences are created when they are running or start within `lookahead`. The events of known occurrences
    are kept in line with the feed, wherever the occurrences moved to. Known occurrences that are over are pruned,
    and those missing from `occurrences` are cancelled: parse_occurrences finds known occurrences wherever they moved
    to, so a missing one was removed from the feed or cancelled in it.
    """
    earliest_start = now + START_DELAY
    handled: set[OccurrenceKey] = set()
    actions: list[Action] = []
    for occurrence in occurrences:
        if occurrence.key in handled:
            continue
        handled.add(occurrence.key)
        if occurrence.key in known and occurrence.end <= now:
            actions.append(Prune(occurrence.key))
            continue
        # Discord needs the end after the start, so an occurrence that ends before Discord would let it start is as
        # good as over
        if occurrence.end <= max(occurrence.start, earliest_start):
            continue

        details = _details(occurrence, earliest_start)
        if occurrence.key not in known:
            # Only created when running now or starting within the lookahead
            if occurrence.start < now + lookahead:
                actions.append(Create(occurrence, details))
            continue

        current = known[occurrence.key]
        if current is None:
            actions.append(Recreate(occurrence, details))
            continue
        if current.start <= now and occurrence.start > earliest_start:
            # Running in Discord, which won't move the start of a running event, while the calendar moved it to later
            actions.append(Recreate(occurrence, details))
            continue
        if occurrence.start <= earliest_start and current.start <= earliest_start:
            # Started both in the calendar and in Discord, so the start in Discord is kept: it can't be moved into the
            # past anyway
            details = replace(details, start=current.start)
        if details != current:
            actions.append(Update(occurrence, details))

    for key in sorted(known.keys() - handled):
        # The expansion no longer returns an occurrence of a series once it is over, so a missing one may be over
        actions.append(Prune(key) if ends[key] <= now else Cancel(key))
    return actions


def _details(occurrence: Occurrence, earliest_start: datetime) -> EventDetails:
    return EventDetails(
        name=event_title(occurrence, NAME_LIMIT),
        description=_description(occurrence),
        location=_location(occurrence),
        start=max(occurrence.start, earliest_start),
        end=occurrence.end,
    )


def event_title(occurrence: Occurrence, limit: int = NAME_LIMIT) -> str:
    return cut(occurrence.title.strip() or NO_TITLE, limit)


def _description(occurrence: Occurrence) -> str:
    """The description cut to Discord's limit, followed by the URL when it fits and is not already in there."""
    description = cut(occurrence.description.strip(), DESCRIPTION_LIMIT)
    url = occurrence.url.strip()
    if not url or url in description:
        return description

    with_url = f"{description}\n\n{url}" if description else url
    return with_url if len(with_url) <= DESCRIPTION_LIMIT else description


def _location(occurrence: Occurrence) -> str:
    """The location, else the URL when it fits whole, else a pointer to the description."""
    if occurrence.location.strip():
        return cut(occurrence.location.strip(), LOCATION_LIMIT)
    url = occurrence.url.strip()
    if url and len(url) <= LOCATION_LIMIT:
        return url
    return NO_LOCATION
