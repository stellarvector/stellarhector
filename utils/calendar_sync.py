"""Mirrors the events of the ICS calendar feed into the server's Discord scheduled events.

parse_occurrences, plan, announcement and the /calendar-sync replies are pure: they turn the feed and what the bot already created
into actions. sync downloads the feed and carries the actions out on Discord.
"""
import asyncio
import logging
from collections import namedtuple
from dataclasses import dataclass, replace
from datetime import datetime, time, timedelta, timezone
from typing import NamedTuple
from zoneinfo import ZoneInfo

import aiohttp
import discord
import icalendar
import recurring_ical_events
import x_wr_timezone

import core.db as db
from utils.ctftime import parse_ctftime_id
from utils.text import cut, inline_code
from utils.unfinished import UnfinishedWork

# Discord refuses events that a bot creates with a start in the past, so running events start this much from now
START_DELAY = timedelta(minutes=1)

# Discord's limits for a scheduled event
NAME_LIMIT = 100
DESCRIPTION_LIMIT = 1000
LOCATION_LIMIT = 100

# How much of the description the announcement shows; Discord allows 256 characters in an embed title
EXCERPT_LIMIT = 300
TITLE_LIMIT = 256

# All-day events run from midnight to this time on their last day
END_OF_DAY = time(23, 59)

# The expansion reads dates and floating times in its own timezone, so it gets this much extra on both sides
# of the window; plan makes the exact cut
EXPANSION_MARGIN = timedelta(days=1)

NO_LOCATION = "See description"
NO_TITLE = "Untitled event"

# How much of the reason a skipped /calendar-sync reply shows
REASON_LIMIT = 500

# The reply to the announcement of a cancelled event
CANCELLED_MESSAGE = "❌ This event has been cancelled."

DOWNLOAD_TIMEOUT = aiohttp.ClientTimeout(total=30)

# Syncs skipped in a row before the admins are alerted: 2.5 hours at the default interval
FAILURES_BEFORE_ALERT = 10


# What the bot remembers of an occurrence it created an event for; announcement_message_id is None when not announced,
# and end is the end the occurrence had in the calendar at the last sync
StoredOccurrence = namedtuple("StoredOccurrence", ["discord_event_id", "announcement_message_id", "end"])

# Selects the calendar_occurrences row of an OccurrenceKey; its start column holds the slot
WHERE_KEY = "uid = ? AND start = ?"

# The create and edit work of syncs that were stopped while it ran
_unfinished = UnfinishedWork()


class OccurrenceKey(NamedTuple):
    """What identifies an occurrence across syncs, and its row in calendar_occurrences: its UID and its slot as
    stored (db.time_text), empty for an event that does not recur."""
    uid: str
    slot: str


class FeedError(Exception):
    """The calendar feed could not be downloaded or is not an ICS calendar."""


class EmptyFeed(FeedError):
    """The calendar feed has no events while the bot manages some: more likely a hiccup of the calendar provider
    than every event being cancelled at once."""


@dataclass(frozen=True)
class Occurrence:
    """One occurrence of a calendar event, with aware start and end.

    slot is the start the occurrence has in its recurring series (its RECURRENCE-ID), which differs from start
    when the occurrence was moved; None for an event that does not recur.
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
    def key(self):
        """What identifies the occurrence across syncs: its UID and its slot in UTC, or only its UID when it does not
        recur, so moving it keeps the key."""
        return OccurrenceKey(self.uid, "" if self.slot is None else db.time_text(self.slot))

    @property
    def ctftime_id(self):
        """The CTFtime event this occurrence is a CTF session of: the one linked in URL, else in the description.
        None for a normal event (meetup etc.)."""
        ctftime_id = parse_ctftime_id(self.url)
        return parse_ctftime_id(self.description) if ctftime_id is None else ctftime_id


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
class Update:
    """Bring the bot's Discord event for occurrence in line with the calendar."""
    occurrence: Occurrence
    details: EventDetails


@dataclass(frozen=True)
class Recreate:
    """Create the bot's Discord event for occurrence again, deleting the one Discord still has: it was deleted in
    Discord, or it is running there while the calendar moved it to later, a start Discord won't move."""
    occurrence: Occurrence
    details: EventDetails


@dataclass(frozen=True)
class Cancel:
    """Delete the bot's Discord event for the occurrence with key and tell the announcement: it is gone from the
    calendar or cancelled there."""
    key: OccurrenceKey


@dataclass(frozen=True)
class Prune:
    """Forget the occurrence with key, deleting its Discord event when that is still there: it is over."""
    key: OccurrenceKey


@dataclass(frozen=True)
class Summary:
    """What one sync changed on Discord."""
    created: int = 0
    updated: int = 0
    cancelled: int = 0


class FeedHealth:
    """Counts the syncs skipped in a row because of the feed, to tell the admins once it has been broken a while.

    Kept in memory only, so a restart starts counting again.
    """

    def __init__(self, alert_after=FAILURES_BEFORE_ALERT):
        self.alert_after = alert_after
        self.failures = 0
        self.alerted = False

    def failed(self):
        """Count a skipped sync. Returns whether the alert is due now: it stays due until alert_posted."""
        self.failures += 1
        return self.failures >= self.alert_after and not self.alerted

    def alert_posted(self):
        self.alerted = True

    def succeeded(self):
        """Start counting again after a successful sync. Returns whether the recovery is due: the admins were alerted
        and not told yet that it works again (recovery_posted)."""
        recovered = self.alerted
        self.failures = 0
        return recovered

    def recovery_posted(self):
        """Stop the recovery being due; until then every successful sync asks for it again."""
        self.alerted = False


def parse_occurrences(ics, tz, now, lookahead, known=frozenset()):
    """The occurrences in the ICS bytes that are running at now or start within lookahead from it, give or take
    a day: plan makes the exact cut. Recurring events are expanded into their occurrences. Times without a timezone
    are in tz, and all-day events run from 00:00 on their first day to 23:59 on their last day in tz.

    The occurrences with a key in known are in there wherever they moved to, as long as they are in the feed.

    Events without a UID or an end, events with properties that can't be read, and cancelled occurrences
    are left out. Raises FeedError when ics is not an ICS calendar, and EmptyFeed when it has no events left
    while known is not empty.
    """
    try:
        calendar = icalendar.Calendar.from_ical(ics)
    except ValueError as e:
        raise FeedError(f"Calendar feed is not a valid ICS calendar: {e}") from e

    # Skipped events are dropped before expanding, so the expansion only meets events it can read
    calendar.subcomponents = [component for component in calendar.subcomponents
                              if component.name != "VEVENT" or _is_usable(component)]
    # The expansion reads floating times in X-WR-TIMEZONE; converted once here, so _find reads them in that zone too
    calendar = _standard(calendar)
    if known and not calendar.walk("VEVENT"):
        raise EmptyFeed(f"Calendar feed has no events while the bot manages {len(known)}, skipped to not cancel them all")

    # The expansion drops RRULE and RDATE, so whether an occurrence belongs to a series is read beforehand
    recurring = {_uid(component) for component in calendar.walk("VEVENT")
                 if any(name in component for name in ("RRULE", "RDATE", "RECURRENCE-ID"))}

    zone = ZoneInfo(tz)
    expanded = _expand(lambda: recurring_ical_events.of(calendar).between(now - EXPANSION_MARGIN,
                                                                           now + lookahead + EXPANSION_MARGIN))

    occurrences = _occurrences(expanded, zone, recurring)
    moved_away = set(known) - {occurrence.key for occurrence in occurrences}
    return occurrences + [occurrence for key in moved_away for occurrence in _find(calendar, key, zone, recurring)]


def _occurrences(expanded, zone, recurring):
    # Cancelled occurrences, also single ones of a series, are left out as if they were not in the feed
    return [_occurrence(event, zone, recurring) for event in expanded
            if str(event.get("STATUS", "")).upper() != "CANCELLED"]


def _find(calendar, key, zone, recurring):
    """The occurrence with key wherever it is in time, in a list that is empty when it is not in the calendar.

    An occurrence outside the window is a one-off event or an override in a series (RECURRENCE-ID) that was moved,
    or an occurrence a series' rule makes at its slot, which was in the window when the window was longer.
    """
    uid, slot = key
    events = [component for component in calendar.walk("VEVENT") if _uid(component) == uid]
    if uid not in recurring and slot:
        return []
    overrides = [event for event in events if "RECURRENCE-ID" in event
                 and db.time_text(_slot(event.decoded("RECURRENCE-ID"), zone)) == slot]

    # The event on its own, with the calendar's timezones, so expanding it gives just its occurrences
    alone = icalendar.Calendar(calendar)
    others = [component for component in calendar.subcomponents if component.name != "VEVENT"]
    if uid not in recurring or overrides:
        alone.subcomponents = others + (overrides or events)
        expansion = lambda: recurring_ical_events.of(alone).all()
    else:
        # The rule goes on forever, so the series is only expanded around the slot
        alone.subcomponents = others + events
        start = db.parse_time(slot)
        expansion = lambda: recurring_ical_events.of(alone).between(start - EXPANSION_MARGIN, start + EXPANSION_MARGIN)
    return [occurrence for occurrence in _occurrences(_expand(expansion), zone, recurring) if occurrence.key == key]


def _standard(calendar):
    """calendar with the floating times read in its X-WR-TIMEZONE, when it has one. Raises FeedError when that
    timezone is unknown."""
    try:
        return x_wr_timezone.to_standard(calendar)
    except (KeyError, ValueError) as e:
        raise FeedError(f"Calendar feed has an unknown X-WR-TIMEZONE: {e!r}") from e


def _expand(expansion):
    """The events expansion returns. Raises FeedError when the calendar can't be expanded."""
    try:
        return expansion()
    except (recurring_ical_events.InvalidCalendar, ValueError) as e:
        raise FeedError(f"Calendar feed could not be expanded: {e!r}") from e


def _uid(event):
    return str(event["UID"]).strip()


def _is_usable(event):
    """Whether the event has what an occurrence needs; logs why when it is skipped."""
    uid = str(event.get("UID", "")).strip()
    summary = str(event.get("SUMMARY", ""))
    if not uid:
        logging.getLogger("bot").warning(f"Calendar event {summary!r} has no UID, skipped")
        return False
    if event.errors:
        # icalendar keeps going on values it can't read, leaving them as plain text
        logging.getLogger("bot").warning(f"Calendar event {uid} ({summary!r}) has unreadable properties {event.errors}, skipped")
        return False
    if "DTSTART" not in event:
        logging.getLogger("bot").warning(f"Calendar event {uid} ({summary!r}) has no start, skipped")
        return False

    start = event.decoded("DTSTART")
    if "DTEND" in event:
        # A timed start with an all-day end, or the other way around, is not a period
        if isinstance(event.decoded("DTEND"), datetime) != isinstance(start, datetime):
            logging.getLogger("bot").warning(f"Calendar event {uid} ({summary!r}) mixes a date and a time, skipped")
            return False
        return True
    # An all-day event without an end lasts one day; a timed one has no end the bot can use
    if "DURATION" not in event and isinstance(start, datetime):
        logging.getLogger("bot").warning(f"Calendar event {uid} ({summary!r}) has no end, skipped")
        return False
    return True


def _occurrence(event, zone, recurring):
    """The Occurrence of one expanded event, which always has DTSTART, DTEND and RECURRENCE-ID.
    recurring holds the UIDs of the events that recur."""
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


def _slot(recurrence_id, zone):
    if isinstance(recurrence_id, datetime):
        return _to_utc(recurrence_id, zone)
    return _start_of_day(recurrence_id, zone)


def _to_utc(moment, zone):
    """moment in UTC, reading a floating time as one in zone."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=zone)
    return moment.astimezone(timezone.utc)


def _start_of_day(day, zone):
    return datetime.combine(day, time(), zone)


def _end_of_day(day, zone):
    return datetime.combine(day, END_OF_DAY, zone)


def plan(occurrences, known, ends, now, lookahead):
    """The actions that bring Discord in line with the feed. known maps the key of each occurrence the bot
    already created an event for to the EventDetails that event has in Discord now, or None when it is gone
    from Discord; ends maps those keys to the end the occurrence had in the calendar at the last sync.

    New occurrences are created when they are in scope; the events of known ones are kept matching the feed
    wherever they moved to. Known occurrences that are over are pruned, and the ones missing from occurrences
    are cancelled: parse_occurrences finds known occurrences wherever they moved to, so they are gone from the feed
    or cancelled in it.
    """
    earliest_start = now + START_DELAY
    handled = set()
    actions = []
    for occurrence in occurrences:
        if occurrence.key in handled:
            continue
        handled.add(occurrence.key)
        if occurrence.key in known and occurrence.end <= now:
            actions.append(Prune(occurrence.key))
            continue
        # Discord needs the end after the start, so one ending before Discord would let it start is as good as over
        if occurrence.end <= max(occurrence.start, earliest_start):
            continue

        details = _details(occurrence, earliest_start)
        if occurrence.key not in known:
            # In scope: running now or starting within the window
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
            # Started both in the calendar and in Discord: the start Discord has can't be put in the past anyway
            details = replace(details, start=current.start)
        if details != current:
            actions.append(Update(occurrence, details))

    for key in sorted(known.keys() - handled):
        # An occurrence of a series is no longer in the feed once it is over, as far as the expansion goes
        actions.append(Prune(key) if ends[key] <= now else Cancel(key))
    return actions


def announcement(action, event_url, ping_role=None):
    """The content, embed and allowed mentions announcing the event created for action.

    Only ping_role is mentioned (nobody when it is None); everything from the calendar sits in the embed.
    """
    occurrence = action.occurrence
    embed = discord.Embed(
        title=_title(occurrence, TITLE_LIMIT),
        url=event_url,
        description=cut(occurrence.description.strip(), EXCERPT_LIMIT) or None,
    )
    embed.add_field(name="Start", value=_timestamp(occurrence.start), inline=False)
    embed.add_field(name="End", value=_timestamp(occurrence.end), inline=False)
    embed.add_field(name="Location", value=action.details.location, inline=False)
    embed.add_field(name="Event", value=f"[Open in Discord]({event_url})", inline=False)

    if ping_role is None:
        return None, embed, discord.AllowedMentions.none()
    return f"<@&{ping_role.id}>", embed, discord.AllowedMentions(everyone=False, users=False, roles=[ping_role])


def summary_reply(summary):
    """The /calendar-sync reply after a sync."""
    return (f":white_check_mark: Calendar synced: {summary.created} created, {summary.updated} updated,"
            f" {summary.cancelled} cancelled.")


def skipped_reply(error):
    """The /calendar-sync reply when the sync was skipped because of the FeedError error."""
    return f":warning: Calendar sync skipped, nothing changed. Reason: {inline_code(str(error), REASON_LIMIT)}"


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
    return cut(occurrence.title.strip() or NO_TITLE, limit)


def _description(occurrence):
    """DESCRIPTION cut to Discord's limit, followed by URL when it fits and is not in there yet."""
    description = cut(occurrence.description.strip(), DESCRIPTION_LIMIT)
    url = occurrence.url.strip()
    if not url or url in description:
        return description

    with_url = f"{description}\n\n{url}" if description else url
    return with_url if len(with_url) <= DESCRIPTION_LIMIT else description


def _location(occurrence):
    """LOCATION, else URL when it fits whole, else a pointer to the description."""
    if occurrence.location.strip():
        return cut(occurrence.location.strip(), LOCATION_LIMIT)
    url = occurrence.url.strip()
    if url and len(url) <= LOCATION_LIMIT:
        return url
    return NO_LOCATION


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
    """Download the feed and bring the bot's Discord events in line with it: create an event, with an announcement
    in announce_channel when it is set, for every occurrence in scope that has none yet, quietly update or
    recreate the events the bot created before, and delete the ones cancelled in the calendar with a reply to their
    announcement. Occurrences that are over are forgotten, and their events quietly deleted when Discord still has
    them. What the calendar has for the occurrences the bot has an event for is remembered (remember_occurrences).
    Returns a Summary.

    Raises FeedError, before anything changes, when the feed can't be downloaded or parsed, EmptyFeed (a FeedError)
    when it has no events while the bot manages some, and discord.HTTPException
    when the server's events can't be read. An event that Discord refuses is logged and tried again on the next sync.
    """
    # A sync that was stopped may still be creating or editing; wait for it, so its event is not created again
    await _unfinished.wait()

    now = datetime.now(timezone.utc)
    stored = _stored_occurrences()
    occurrences = parse_occurrences(await fetch(ics_url), tz, now, lookahead, stored.keys())
    events = await _events(guild, stored)
    in_discord = {key: None if event is None else _details_in_discord(event) for key, event in events.items()}
    ends = {key: occurrence.end for key, occurrence in stored.items()}
    actions = plan(occurrences, in_discord, ends, now, lookahead)

    created = updated = cancelled = 0
    for action in actions:
        if isinstance(action, Prune):
            await _delete_and_forget(events[action.key], action.key)
            continue
        if isinstance(action, Cancel):
            if await _cancel(events[action.key], announce_channel, stored[action.key].announcement_message_id, action.key):
                cancelled += 1
            continue

        key = action.occurrence.key
        try:
            if isinstance(action, Update):
                event = await _update(events[key], action)
            else:
                event = await _create(guild, action, events.get(key))
        except discord.HTTPException:
            logging.getLogger("bot").exception(f"Discord refused the event for calendar occurrence {key}")
            continue
        if event is None:
            continue

        if isinstance(action, Create):
            created += 1
            if announce_channel is not None:
                await _announce(announce_channel, action, event, ping_role)
        else:
            updated += 1
            # The announcement quietly follows the event, the link included when it was recreated
            message_id = stored[key].announcement_message_id
            if announce_channel is not None and message_id is not None:
                await _edit_announcement(announce_channel, message_id, action, event, ping_role)

    remember_occurrences(occurrences)
    return Summary(created=created, updated=updated, cancelled=cancelled)


def remember_occurrences(occurrences):
    """Store the start, title (as the event is named) and CTFtime link each occurrence has in the calendar now,
    for the occurrences the bot has an event for; the daily CTFtime check reads the CTF sessions from there.
    Like plan, the first of an occurrence listed twice wins."""
    remembered = set()
    with db.transaction() as conn:
        for occurrence in occurrences:
            if occurrence.key in remembered:
                continue
            remembered.add(occurrence.key)
            values = (db.time_text(occurrence.start), _title(occurrence, NAME_LIMIT), occurrence.ctftime_id)
            # Only written when something changed, so a sync that changes nothing writes nothing
            conn.execute(f"UPDATE calendar_occurrences SET start_time = ?, title = ?, ctftime_id = ? WHERE {WHERE_KEY}"
                         " AND (start_time IS NOT ? OR title IS NOT ? OR ctftime_id IS NOT ?)",
                         (*values, *occurrence.key, *values))


def _details_in_discord(event):
    """The EventDetails a Discord event has now."""
    return EventDetails(
        name=event.name,
        description=event.description or "",
        location=event.location or "",
        start=event.start_time,
        end=event.end_time,
    )


async def _events(guild, stored):
    """The bot's Discord event per stored occurrence key, None when it is no longer scheduled or running."""
    if not stored:
        return {}
    live = {event.id: event for event in await guild.fetch_scheduled_events(with_counts=False)
            if event.status in (discord.EventStatus.scheduled, discord.EventStatus.active)}
    return {key: live.get(occurrence.discord_event_id) for key, occurrence in stored.items()}


def _start(action):
    """When the event for action starts in Discord, or None when it would not end after that start.

    Earlier actions may have waited on Discord's rate limit, so a start moved to now + START_DELAY
    while planning can be in the past by now.
    """
    start = max(action.details.start, datetime.now(timezone.utc) + START_DELAY)
    return start if start < action.details.end else None


async def _create(guild, action, replaced=None):
    """The new Discord event for a Create or Recreate action, or None when it is too late to create it. replaced is
    the event Discord still has for a Recreate, deleted first so the occurrence never has two.

    The event is remembered right away, with no await in between, so the next sync can't create it again.
    """
    start = _start(action)
    if start is None:
        return None

    if replaced is not None:
        try:
            await replaced.delete()
        except discord.NotFound:
            pass

    async def create_and_remember():
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
        key = action.occurrence.key
        end = db.time_text(action.occurrence.end)
        try:
            with db.transaction() as conn:
                if isinstance(action, Recreate):
                    conn.execute(f"UPDATE calendar_occurrences SET discord_event_id = ?, end_time = ? WHERE {WHERE_KEY}",
                                 (event.id, end, *key))
                else:
                    conn.execute("INSERT INTO calendar_occurrences (uid, start, discord_event_id, end_time) VALUES (?, ?, ?, ?)",
                                 (*key, event.id, end))
        except Exception:
            # An event the bot doesn't remember would be created again on the next sync and never be cleaned up
            try:
                await event.delete()
            except discord.HTTPException:
                logging.getLogger("bot").exception(f"Could not delete the unremembered event {event.id} of calendar occurrence {key}")
            raise
        return event

    # Shielded: when the job times out mid-create, the event is still remembered once Discord made it
    return await _unfinished.finish_even_if_stopped(create_and_remember())


async def _update(event, action):
    """event edited to match action, with the occurrence's new end remembered, or None when it is too late to move
    its start."""
    details = action.details
    changes = {}
    # The start is only sent when it changed, and never for a running event: Discord won't move its start
    if details.start != event.start_time and event.status is discord.EventStatus.scheduled:
        start = _start(action)
        if start is None:
            return None
        changes["start_time"] = start

    async def edit_and_remember():
        edited = await event.edit(name=details.name, description=details.description, location=details.location,
                                  end_time=details.end, **changes)
        with db.transaction() as conn:
            conn.execute(f"UPDATE calendar_occurrences SET end_time = ? WHERE {WHERE_KEY}",
                         (db.time_text(action.occurrence.end), *action.occurrence.key))
        return edited

    # Shielded like create_and_remember, so the end stays the one Discord has
    return await _unfinished.finish_even_if_stopped(edit_and_remember())


async def _cancel(event, channel, message_id, key):
    """Delete event when it is still in Discord, forget the occurrence and reply to its announcement. Returns whether
    it was cancelled: when Discord refuses the delete, it is tried again on the next sync.

    The occurrence is forgotten before replying, so the reply is posted at most once; a failed reply is only logged.
    """
    if not await _delete_and_forget(event, key):
        return False

    if channel is not None and message_id is not None:
        try:
            await channel.get_partial_message(message_id).reply(CANCELLED_MESSAGE, mention_author=False,
                                                                allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            logging.getLogger("bot").exception(f"Could not reply to the announcement of cancelled calendar occurrence {key}")
    return True


async def _delete_and_forget(event, key):
    """Delete event when it is still in Discord and forget the occurrence with key. Returns False when Discord refused
    the delete: that is logged, and the occurrence is kept so the next sync tries again."""
    if event is not None:
        try:
            await event.delete()
        except discord.NotFound:
            pass
        except discord.HTTPException:
            logging.getLogger("bot").exception(f"Discord refused deleting the event for calendar occurrence {key}")
            return False

    with db.transaction() as conn:
        conn.execute(f"DELETE FROM calendar_occurrences WHERE {WHERE_KEY}", key)
    return True


async def _announce(channel, action, event, ping_role):
    """Post the announcement; a failure is logged and not retried, the event itself is in place."""
    content, embed, allowed_mentions = announcement(action, event.url, ping_role)
    try:
        message = await channel.send(content, embed=embed, allowed_mentions=allowed_mentions)
    except discord.HTTPException:
        logging.getLogger("bot").exception(f"Could not announce calendar event {event.id}")
        return

    with db.transaction() as conn:
        conn.execute(f"UPDATE calendar_occurrences SET announcement_message_id = ? WHERE {WHERE_KEY}",
                     (message.id, *action.occurrence.key))


async def _edit_announcement(channel, message_id, action, event, ping_role):
    """Edit the announcement to show event as it is now, pinging nobody again; a failure is logged."""
    _, embed, _ = announcement(action, event.url, ping_role)
    try:
        await channel.get_partial_message(message_id).edit(embed=embed)
    except discord.HTTPException:
        logging.getLogger("bot").exception(f"Could not edit the announcement of calendar event {event.id}")


def _stored_occurrences():
    """The StoredOccurrence per occurrence key the bot created an event for."""
    with db.transaction() as conn:
        return {OccurrenceKey(row["uid"], row["start"]): StoredOccurrence(row["discord_event_id"],
                                                                          row["announcement_message_id"],
                                                                          db.parse_time(row["end_time"]))
                for row in conn.execute("SELECT uid, start, discord_event_id, announcement_message_id, end_time "
                                        "FROM calendar_occurrences")}
