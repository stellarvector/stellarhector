"""Looking up and deleting Discord objects the way the CTF features need it: from the cache when there, else from
Discord, and None for what is gone."""
import logging

import discord


async def member(guild, user_id):
    """The member with this ID, or None when they are no longer on the server."""
    found = guild.get_member(user_id)
    if found is not None:
        return found
    try:
        return await guild.fetch_member(user_id)
    except discord.NotFound:
        return None


async def thread(guild, thread_id):
    """The thread with this ID, also when it is archived (and so not in the cache), or None when it was deleted."""
    found = guild.get_channel_or_thread(thread_id)
    if found is not None:
        return found
    try:
        return await guild.fetch_channel(thread_id)
    except discord.NotFound:
        return None


async def all_threads(channel):
    """All threads of the channel, also made by hand: the active ones and the archived public and private ones, oldest
    first. A channel that can't have threads (e.g. a voice channel) has none."""
    if not hasattr(channel, "archived_threads"):
        return []
    threads = {thread.id: thread for thread in channel.threads}
    for private in (False, True):
        threads.update({thread.id: thread async for thread in channel.archived_threads(private=private, limit=None)})
    return sorted(threads.values(), key=lambda thread: thread.id)


async def delete_all(discord_objects, of_what):
    """Delete each of the Discord objects, in order, that exists (None is skipped). A failure is logged as of_what
    (e.g. "of a removed CTF") and the rest is still deleted. Returns the names of the ones that could not be
    deleted."""
    not_deleted = []
    for discord_object in discord_objects:
        if discord_object is None:
            continue
        try:
            await discord_object.delete()
        except Exception:
            logging.getLogger("bot").exception(f"Could not delete {discord_object!r} {of_what}")
            not_deleted.append(f"`{getattr(discord_object, 'name', discord_object.id)}`")
    return not_deleted
