"""Looking up and deleting Discord objects: from the cache when they are there, else from Discord, and None for objects
that are gone."""

import logging
from collections.abc import Iterable
from typing import cast

import discord

log = logging.getLogger("bot")

Deletable = discord.abc.GuildChannel | discord.Thread | discord.Role | discord.Message


async def member(guild: discord.Guild, user_id: int) -> discord.Member | None:
    found = guild.get_member(user_id)
    if found is not None:
        return found
    try:
        return await guild.fetch_member(user_id)
    except discord.NotFound:
        return None


async def thread(guild: discord.Guild, thread_id: int) -> discord.Thread | None:
    # An archived thread isn't in the cache, so it is fetched
    found = guild.get_channel_or_thread(thread_id)
    if found is not None:
        return cast(discord.Thread, found)
    try:
        return cast(discord.Thread, await guild.fetch_channel(thread_id))
    except discord.NotFound:
        return None


async def all_threads(channel: discord.abc.GuildChannel) -> list[discord.Thread]:
    """All threads of `channel`, oldest first: the active ones and the archived public and private ones, including
    threads made by hand. A channel that can't have threads, such as a voice channel, has none."""
    if not hasattr(channel, "archived_threads"):
        return []
    if isinstance(channel, discord.ForumChannel):
        # A forum's posts are public threads; it has no private archived ones to ask for
        threads = {thread.id: thread for thread in channel.threads}
        threads.update({thread.id: thread async for thread in channel.archived_threads(limit=None)})
        return sorted(threads.values(), key=lambda thread: thread.id)

    text_channel = cast(discord.TextChannel, channel)
    threads = {thread.id: thread for thread in text_channel.threads}
    for private in (False, True):
        threads.update(
            {thread.id: thread async for thread in text_channel.archived_threads(private=private, limit=None)}
        )
    return sorted(threads.values(), key=lambda thread: thread.id)


async def delete_all(discord_objects: Iterable[Deletable | None], of_what: str) -> list[str]:
    """Delete the objects in order, skipping None. A failure is logged with `of_what` (for example "of a removed CTF")
    and the rest is still deleted. Returns the names of the objects that could not be deleted."""
    not_deleted = []
    for discord_object in discord_objects:
        if discord_object is None:
            continue
        try:
            await discord_object.delete()
        except Exception:
            log.exception(f"Could not delete {discord_object!r} {of_what}")
            not_deleted.append(f"`{getattr(discord_object, 'name', discord_object.id)}`")
    return not_deleted
