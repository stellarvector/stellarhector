"""Mirrors the events of the ICS calendar feed into the server's Discord scheduled events.

parse_occurrences, plan and announcement are pure: they turn the feed and what the bot already created
into actions. sync downloads the feed and carries the actions out on Discord.
"""
import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import aiohttp
import discord
import icalendar

import core.db as db

# Discord refuses events that a bot creates with a start in the past, so running events start this much from now
START_DELAY = timedelta(minutes=1)

# Discord's limits for a scheduled event
NAME_LIMIT = 100
DESCRIPTION_LIMIT = 1000
LOCATION_LIMIT = 100

# How much of the description the announcement shows; Discord allows 256 characters in an embed title
EXCERPT_LIMIT = 300
TITLE_LIMIT = 256

NO_LOCATION = "See description"
NO_TITLE = "Untitled event"

DOWNLOAD_TIMEOUT = aiohttp.ClientTimeout(total=30)


class FeedError(Exception):
    """The calendar feed could not be downloaded or is not an ICS calendar."""


@dataclass(frozen=True)
class Occurrence:
    """One occurrence of a calendar event, with aware start and end."""
    uid: str
    start: datetime
    end: datetime
    title: str
    description: str = ""
    location: str = ""
    url: str = ""

    @property
    def key(self):
        """What identifies the occurrence across syncs: its UID and its start in UTC."""
        return self.uid, self.start.astimezone(timezone.utc).isoformat()


@dataclass(frozen=True)
class EventDetails:
    """What a Discord scheduled event is created with."""
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
class Summary:
    """What one sync changed on Discord."""
    created: int = 0
    updated: int = 0
    cancelled: int = 0


def parse_occurrences(ics, tz):
    """The occurrences of the single, timed events in the ICS bytes. Times without a timezone are in tz.

    Events without a UID or an end are skipped. Recurring and all-day events are not supported yet.
    Raises FeedError when ics is not an ICS calendar.
    """
    try:
        calendar = icalendar.Calendar.from_ical(ics)
    except ValueError as e:
        raise FeedError(f"Calendar feed is not a valid ICS calendar: {e}") from e

    occurrences = []
    for event in calendar.walk("VEVENT"):
        occurrence = _parse_event(event, ZoneInfo(tz))
        if occurrence is not None:
            occurrences.append(occurrence)
    return occurrences


def _parse_event(event, zone):
    uid = str(event.get("UID", "")).strip()
    summary = str(event.get("SUMMARY", ""))
    if not uid:
        logging.getLogger("bot").warning(f"Calendar event {summary!r} has no UID, skipped")
        return None
    if event.errors:
        # icalendar keeps going on values it can't read, leaving them as plain text
        logging.getLogger("bot").warning(f"Calendar event {uid} ({summary!r}) has unreadable properties {event.errors}, skipped")
        return None
    # Cancelled events are left out, as if they were not in the feed
    if "RRULE" in event or "RECURRENCE-ID" in event or "DTSTART" not in event or event.get("STATUS") == "CANCELLED":
        return None

    start = event.decoded("DTSTART")
    if not isinstance(start, datetime):
        return None

    # icalendar makes up an end when there is none, so look for one first
    if "DTEND" in event:
        end = event.decoded("DTEND")
        if not isinstance(end, datetime):
            return None
    elif "DURATION" in event:
        end = start + event.decoded("DURATION")
    else:
        logging.getLogger("bot").warning(f"Calendar event {uid} ({summary!r}) has no end, skipped")
        return None

    return Occurrence(
        uid=uid,
        start=_to_utc(start, zone),
        end=_to_utc(end, zone),
        title=summary,
        description=str(event.get("DESCRIPTION", "")),
        location=str(event.get("LOCATION", "")),
        url=str(event.get("URL", "")),
    )


def _to_utc(moment, zone):
    """moment in UTC, reading a floating time as one in zone."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=zone)
    return moment.astimezone(timezone.utc)


def plan(occurrences, known, now, lookahead):
    """The actions that bring Discord in line with the feed. known holds the keys of the occurrences
    the bot already created an event for."""
    earliest_start = now + START_DELAY
    handled = set(known)
    actions = []
    for occurrence in occurrences:
        # In scope: running now or starting within the window. Discord needs the end after the start,
        # so one ending before Discord would let it start is as good as over.
        if occurrence.key in handled or occurrence.start >= now + lookahead:
            continue
        if occurrence.end <= max(occurrence.start, earliest_start):
            continue
        handled.add(occurrence.key)
        actions.append(Create(occurrence, _details(occurrence, earliest_start)))
    return actions


def announcement(action, event_url, ping_role=None):
    """The content, embed and allowed mentions announcing the event created for action.

    Only ping_role is mentioned (nobody when it is None); everything from the calendar sits in the embed.
    """
    occurrence = action.occurrence
    embed = discord.Embed(
        title=_title(occurrence, TITLE_LIMIT),
        url=event_url,
        description=_cut(occurrence.description.strip(), EXCERPT_LIMIT) or None,
    )
    embed.add_field(name="Start", value=_timestamp(occurrence.start), inline=False)
    embed.add_field(name="End", value=_timestamp(occurrence.end), inline=False)
    embed.add_field(name="Location", value=action.details.location, inline=False)
    embed.add_field(name="Event", value=f"[Open in Discord]({event_url})", inline=False)

    if ping_role is None:
        return None, embed, discord.AllowedMentions.none()
    return f"<@&{ping_role.id}>", embed, discord.AllowedMentions(everyone=False, users=False, roles=[ping_role])


def _timestamp(moment):
    seconds = int(moment.timestamp())
    return f"<t:{seconds}:F> (<t:{seconds}:R>)"


def _details(occurrence, earliest_start):
    return EventDetails(
        name=_title(occurrence, NAME_LIMIT),
        description=_description(occurrence),
        location=_location(occurrence),
        start=max(occurrence.start, earliest_start),
        end=occurrence.end,
    )


def _title(occurrence, limit):
    return _cut(occurrence.title.strip() or NO_TITLE, limit)


def _description(occurrence):
    """DESCRIPTION cut to Discord's limit, followed by URL when it fits and is not in there yet."""
    description = _cut(occurrence.description.strip(), DESCRIPTION_LIMIT)
    url = occurrence.url.strip()
    if not url or url in description:
        return description

    with_url = f"{description}\n\n{url}" if description else url
    return with_url if len(with_url) <= DESCRIPTION_LIMIT else description


def _location(occurrence):
    """LOCATION, else URL when it fits whole, else a pointer to the description."""
    if occurrence.location.strip():
        return _cut(occurrence.location.strip(), LOCATION_LIMIT)
    url = occurrence.url.strip()
    if url and len(url) <= LOCATION_LIMIT:
        return url
    return NO_LOCATION


def _cut(text, limit):
    return text if len(text) <= limit else text[:limit - 1] + "…"


async def download(url):
    """The calendar feed at url as bytes. Raises FeedError when it can't be downloaded."""
    try:
        async with aiohttp.ClientSession(timeout=DOWNLOAD_TIMEOUT) as session:
            async with session.get(url) as response:
                response.raise_for_status()
                return await response.read()
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        # The URL is left out: a private calendar link holds its secret
        raise FeedError(f"Calendar feed could not be downloaded: {e!r}") from e


async def sync(guild, ics_url, tz, lookahead, announce_channel=None, ping_role=None, fetch=download):
    """Download the feed and create a Discord event, with an announcement in announce_channel when it is set,
    for every occurrence in scope that has none yet. Returns a Summary.

    Raises FeedError, before anything changes, when the feed can't be downloaded or parsed. An event that
    Discord refuses is logged and tried again on the next sync.
    """
    occurrences = parse_occurrences(await fetch(ics_url), tz)
    actions = plan(occurrences, _known_keys(), datetime.now(timezone.utc), lookahead)

    created = 0
    for action in actions:
        # Earlier creates may have waited on Discord's rate limit, so a start moved to now + START_DELAY
        # while planning can be in the past by now
        start = max(action.details.start, datetime.now(timezone.utc) + START_DELAY)
        if start >= action.details.end:
            continue
        try:
            # Shielded: when the job times out mid-create, the event is still remembered once Discord made it
            event = await asyncio.shield(_create_event(guild, action, start))
        except discord.HTTPException:
            logging.getLogger("bot").exception(f"Discord refused the event for calendar occurrence {action.occurrence.key}")
            continue
        created += 1

        if announce_channel is not None:
            await _announce(announce_channel, action, event, ping_role)

    return Summary(created=created)


async def _create_event(guild, action, start):
    """Create the Discord event starting at start and remember it right away, with no await in between,
    so the next sync can't create it again."""
    details = action.details
    event = await guild.create_scheduled_event(
        name=details.name,
        start_time=start,
        end_time=details.end,
        entity_type=discord.EntityType.external,
        privacy_level=discord.PrivacyLevel.guild_only,
        location=details.location,
        description=details.description or discord.utils.MISSING,
    )
    uid, start = action.occurrence.key
    with db.transaction() as conn:
        conn.execute("INSERT INTO calendar_occurrences (uid, start, discord_event_id) VALUES (?, ?, ?)",
                     (uid, start, event.id))
    return event


async def _announce(channel, action, event, ping_role):
    """Post the announcement; a failure is logged and not retried, the event itself is in place."""
    content, embed, allowed_mentions = announcement(action, event.url, ping_role)
    try:
        message = await channel.send(content, embed=embed, allowed_mentions=allowed_mentions)
    except discord.HTTPException:
        logging.getLogger("bot").exception(f"Could not announce calendar event {event.id}")
        return

    uid, start = action.occurrence.key
    with db.transaction() as conn:
        conn.execute("UPDATE calendar_occurrences SET announcement_message_id = ? WHERE uid = ? AND start = ?",
                     (message.id, uid, start))


def _known_keys():
    with db.transaction() as conn:
        return {(row["uid"], row["start"]) for row in conn.execute("SELECT uid, start FROM calendar_occurrences")}
