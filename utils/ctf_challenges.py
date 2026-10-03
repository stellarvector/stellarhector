"""The challenges of a CTF: a public thread each in its category's channel, started with /create-challenge."""
import asyncio
from dataclasses import dataclass

import discord

from utils import ctfs
from utils.ctf_places import Place

# Two runs at the same time could both find a challenge missing and make two threads for it
_lock = asyncio.Lock()

# Discord's longest auto-archive, in minutes: a week, so threads stay in the sidebar during the CTF
_AUTO_ARCHIVE = 10080

NOT_IN_CATEGORY = ("Run this in a category channel of the CTF, or in a challenge thread. "
                   "Create a category channel with `/add-category` in the main channel if needed.")


@dataclass(frozen=True)
class Started:
    """What start did: the challenge's thread, its slug, and whether the thread was created (else it existed)."""
    thread: discord.Thread
    slug: str
    created: bool


def category_of(location):
    """The Category a command run at the Location is in: that of the category channel itself, or of the parent of a
    challenge thread. None anywhere else, also in a channel of the CTF's category not made with /add-category."""
    if location.place not in (Place.CATEGORY, Place.CHALLENGE):
        return None
    return ctfs.category_by_channel(location.ctf.id, location.category_channel.id)


async def start(guild, ctf, category, channel, user, slug):
    """Add the user to the thread of the challenge with this slug in the category, whose channel is given. When the
    challenge has no thread yet, or it was deleted by hand, a starter message is posted in the channel and a public
    thread made on it (named `✅ <slug>` when the challenge is solved), and stored. An archived thread is unarchived
    first. Returns what was Started."""
    async with _lock:
        stored = ctfs.challenge(ctf.id, category.slug, slug)
        thread = None if stored is None else await _thread(guild, stored.thread_id)
        created = thread is None
        if created:
            thread = await _create_thread(channel, user, slug, solved=stored is not None and stored.solved)
            ctfs.add_challenge(ctf.id, category.slug, slug, thread.id)

    if thread.archived:
        await thread.edit(archived=False)
    await thread.add_user(user)
    # TODO ctf-lifecycle 08: update the challenge overview
    return Started(thread, slug, created)


async def _create_thread(channel, user, slug, solved):
    """Post the challenge's starter message in the channel and make a public thread on it, named as solved when the
    challenge is. The message is deleted again when the thread can't be made, and the error raised."""
    message = await channel.send(f"🧩 `{slug}`, started by {user.mention}",
                                 allowed_mentions=discord.AllowedMentions.none())
    try:
        return await message.create_thread(name=f"✅ {slug}" if solved else slug, auto_archive_duration=_AUTO_ARCHIVE)
    except discord.DiscordException:
        await message.delete()
        raise


async def _thread(guild, thread_id):
    """The thread with this ID, also when it is archived (and so not in the cache), or None when it was deleted."""
    thread = guild.get_channel_or_thread(thread_id)
    if thread is not None:
        return thread
    try:
        return await guild.fetch_channel(thread_id)
    except discord.NotFound:
        return None


def reply(started):
    """The reply to the user about what was Started."""
    if started.created:
        return f"Started {started.thread.mention}, go solve that thing :muscle:"
    return f"`{started.slug}` already exists, you were added to {started.thread.mention}"
