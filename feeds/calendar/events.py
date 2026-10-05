"""Mirroring the calendar into the server's Discord scheduled events, with an announcement for each new event."""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast

import aiohttp
import discord

from feeds import FeedError
from feeds.calendar import store
from feeds.calendar.parse import OccurrenceKey, parse_occurrences
from feeds.calendar.plan import (
    START_DELAY,
    Cancel,
    Create,
    EventDetails,
    Prune,
    Recreate,
    Update,
    event_title,
    plan_discord_changes,
)
from feeds.calendar.store import StoredOccurrence
from utils.text import cut
from utils.unfinished import UnfinishedWork

log = logging.getLogger("bot")

# How much of the description the announcement shows
EXCERPT_LIMIT = 300
# Discord's limit for an embed title
TITLE_LIMIT = 256
CANCELLED_MESSAGE = "❌ This event has been cancelled."
DOWNLOAD_TIMEOUT = aiohttp.ClientTimeout(total=30)

# The creates and edits of syncs that were stopped halfway
_unfinished = UnfinishedWork()

Fetch = Callable[[str], Awaitable[bytes]]


@dataclass(frozen=True)
class SyncSummary:
    created: int = 0
    updated: int = 0
    cancelled: int = 0


def announcement(
    action: Create | Recreate | Update, event_url: str, ping_role: discord.Role | None = None
) -> tuple[str | None, discord.Embed, discord.AllowedMentions]:
    """The content, embed and allowed mentions of the announcement. Only `ping_role` is mentioned; everything from the
    calendar goes in the embed."""
    occurrence = action.occurrence
    embed = discord.Embed(
        title=event_title(occurrence, TITLE_LIMIT),
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


def _timestamp(moment: datetime) -> str:
    seconds = int(moment.timestamp())
    return f"<t:{seconds}:F> (<t:{seconds}:R>)"


async def download(url: str) -> bytes:
    try:
        async with aiohttp.ClientSession(timeout=DOWNLOAD_TIMEOUT) as session:
            async with session.get(url) as response:
                response.raise_for_status()
                return await response.read()
    except (TimeoutError, aiohttp.ClientError) as e:
        # The URL is left out: a private calendar link contains its secret
        raise FeedError(f"Calendar feed could not be downloaded: {e!r}") from e


async def sync(
    guild: discord.Guild,
    ics_url: str,
    tz: str,
    lookahead: timedelta,
    announce_channel: discord.TextChannel | None = None,
    ping_role: discord.Role | None = None,
    fetch: Fetch = download,
) -> SyncSummary:
    """Bring the bot's Discord events in line with the calendar feed: create (and announce) new ones, quietly update
    or recreate existing ones, delete cancelled ones with a reply to their announcement, and forget the ones that
    are over.

    Raises FeedError before changing anything when the feed can't be read or is suspiciously empty. An event Discord
    refuses is logged and retried on the next sync.
    """
    # A sync that was stopped may still be creating or editing; wait for it, so its event is not created twice
    await _unfinished.wait()

    now = datetime.now(UTC)
    stored = store.stored_occurrences()
    occurrences = parse_occurrences(await fetch(ics_url), tz, now, lookahead, stored.keys())
    events = await _events(guild, stored)
    in_discord = {key: None if event is None else _details_in_discord(event) for key, event in events.items()}
    ends = {key: occurrence.end for key, occurrence in stored.items()}

    created = updated = cancelled = 0
    for action in plan_discord_changes(occurrences, in_discord, ends, now, lookahead):
        if isinstance(action, Prune):
            await _delete_and_forget(events[action.key], action.key)
            continue
        if isinstance(action, Cancel):
            message_id = stored[action.key].announcement_message_id
            if await _cancel(events[action.key], announce_channel, message_id, action.key):
                cancelled += 1
            continue

        key = action.occurrence.key
        try:
            if isinstance(action, Update):
                # plan_discord_changes only updates events Discord still has
                event = await _update(cast(discord.ScheduledEvent, events[key]), action)
            else:
                event = await _create(guild, action, events.get(key))
        except discord.HTTPException:
            log.exception(f"Discord refused the event for calendar occurrence {key}")
            continue
        if event is None:
            continue

        if isinstance(action, Create):
            created += 1
            if announce_channel is not None:
                await _announce(announce_channel, action, event, ping_role)
        else:
            updated += 1
            # The announcement quietly follows the event, including its new link when it was recreated
            message_id = stored[key].announcement_message_id
            if announce_channel is not None and message_id is not None:
                await _edit_announcement(announce_channel, message_id, action, event, ping_role)

    store.remember_details(occurrences, event_title)
    return SyncSummary(created=created, updated=updated, cancelled=cancelled)


def _details_in_discord(event: discord.ScheduledEvent) -> EventDetails:
    return EventDetails(
        name=event.name,
        description=event.description or "",
        location=event.location or "",
        start=event.start_time,
        # External events, the only kind the bot creates, always have an end
        end=cast(datetime, event.end_time),
    )


async def _events(
    guild: discord.Guild, stored: dict[OccurrenceKey, StoredOccurrence]
) -> dict[OccurrenceKey, discord.ScheduledEvent | None]:
    """The bot's Discord event per stored occurrence; None when it is no longer scheduled or running."""
    if not stored:
        return {}
    live = {
        event.id: event
        for event in await guild.fetch_scheduled_events(with_counts=False)
        if event.status in (discord.EventStatus.scheduled, discord.EventStatus.active)
    }
    return {key: live.get(occurrence.discord_event_id) for key, occurrence in stored.items()}


def _start(action: Create | Recreate | Update) -> datetime | None:
    """When the event starts in Discord, or None when it would end before that. Earlier actions may have waited on
    Discord's rate limit, so a start that was planned as now + START_DELAY may already be in the past."""
    start = max(action.details.start, datetime.now(UTC) + START_DELAY)
    return start if start < action.details.end else None


async def _create(
    guild: discord.Guild, action: Create | Recreate, replaced: discord.ScheduledEvent | None = None
) -> discord.ScheduledEvent | None:
    """Create the event, deleting `replaced` first so an occurrence never has two. Returns None when it is too late to
    create it."""
    start = _start(action)
    if start is None:
        return None

    if replaced is not None:
        try:
            await replaced.delete()
        except discord.NotFound:
            pass

    async def create_and_remember() -> discord.ScheduledEvent:
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
        try:
            # Stored with no await in between, so the next sync can't create it again
            if isinstance(action, Recreate):
                store.replace_event(key, event.id, action.occurrence.end)
            else:
                store.add_event(key, event.id, action.occurrence.end)
        except Exception:
            # An event the bot doesn't remember would be created again on every sync and never cleaned up
            try:
                await event.delete()
            except discord.HTTPException:
                log.exception(f"Could not delete the unremembered event {event.id} of calendar occurrence {key}")
            raise
        return event

    # Shielded: when the sync times out mid-create, the event Discord made is still remembered
    return await _unfinished.finish_even_if_stopped(create_and_remember())


async def _update(event: discord.ScheduledEvent, action: Update) -> discord.ScheduledEvent | None:
    """Returns None when it is too late to move the event's start."""
    details = action.details
    new_start = None
    # Only a changed start is sent, and never for a running event: Discord won't move its start
    if details.start != event.start_time and event.status is discord.EventStatus.scheduled:
        new_start = _start(action)
        if new_start is None:
            return None

    async def edit_and_remember() -> discord.ScheduledEvent:
        if new_start is None:
            edited = await event.edit(
                name=details.name, description=details.description, location=details.location, end_time=details.end
            )
        else:
            edited = await event.edit(
                name=details.name,
                description=details.description,
                location=details.location,
                end_time=details.end,
                start_time=new_start,
            )
        store.set_end(action.occurrence.key, action.occurrence.end)
        return edited

    # Shielded like create_and_remember, so the stored end stays the one Discord has
    return await _unfinished.finish_even_if_stopped(edit_and_remember())


async def _cancel(
    event: discord.ScheduledEvent | None,
    channel: discord.TextChannel | None,
    message_id: int | None,
    key: OccurrenceKey,
) -> bool:
    """Returns False when Discord refused the delete; it is retried on the next sync. The occurrence is forgotten
    before replying to the announcement, so the reply is posted at most once."""
    if not await _delete_and_forget(event, key):
        return False

    if channel is not None and message_id is not None:
        try:
            await channel.get_partial_message(message_id).reply(
                CANCELLED_MESSAGE, mention_author=False, allowed_mentions=discord.AllowedMentions.none()
            )
        except discord.HTTPException:
            log.exception(f"Could not reply to the announcement of cancelled calendar occurrence {key}")
    return True


async def _delete_and_forget(event: discord.ScheduledEvent | None, key: OccurrenceKey) -> bool:
    """Returns False when Discord refused the delete; the occurrence is kept so the next sync retries it."""
    if event is not None:
        try:
            await event.delete()
        except discord.NotFound:
            pass
        except discord.HTTPException:
            log.exception(f"Discord refused deleting the event for calendar occurrence {key}")
            return False

    store.forget(key)
    return True


async def _announce(
    channel: discord.TextChannel, action: Create, event: discord.ScheduledEvent, ping_role: discord.Role | None
) -> None:
    # A failed announcement is not retried: the event itself is in place
    content, embed, allowed_mentions = announcement(action, event.url, ping_role)
    try:
        message = await channel.send(content, embed=embed, allowed_mentions=allowed_mentions)
    except discord.HTTPException:
        log.exception(f"Could not announce calendar event {event.id}")
        return
    store.set_announcement(action.occurrence.key, message.id)


async def _edit_announcement(
    channel: discord.TextChannel,
    message_id: int,
    action: Recreate | Update,
    event: discord.ScheduledEvent,
    ping_role: discord.Role | None,
) -> None:
    _, embed, _ = announcement(action, event.url, ping_role)
    try:
        await channel.get_partial_message(message_id).edit(embed=embed)
    except discord.HTTPException:
        log.exception(f"Could not edit the announcement of calendar event {event.id}")
