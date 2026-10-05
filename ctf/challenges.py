"""The challenges of a CTF: a public thread each in its category's channel, started with /create-challenge."""

import asyncio
from dataclasses import dataclass
from typing import Literal, cast

import discord

from ctf import overview, store
from ctf.location import Channel, Location, Place
from ctf.models import Category, Challenge, Ctf
from utils import discord_objects

# Two concurrent runs could both find a challenge missing and create two threads for it
_lock = asyncio.Lock()

# Discord's longest auto-archive duration in minutes (a week), so threads stay in the sidebar during the CTF
_AUTO_ARCHIVE: Literal[10080] = 10080


@dataclass(frozen=True)
class Started:
    thread: discord.Thread
    slug: str
    # False when the thread already existed
    created: bool


def challenge_at(location: Location, channel: Channel | None) -> Challenge | None:
    """Returns None for a thread in a category channel that was not made with /create-challenge."""
    if location.place is not Place.CHALLENGE or location.ctf is None or channel is None:
        return None
    return store.challenge_by_thread(location.ctf.id, channel.id)


def category_of(location: Location) -> Category | None:
    """Returns the category of the category channel itself, or of the parent channel of a challenge thread. Returns
    None anywhere else, including channels in the CTF's category that were not made with /add-category."""
    if location.place not in (Place.CATEGORY, Place.CHALLENGE):
        return None
    if location.ctf is None or location.category_channel is None:
        return None
    return store.category_by_channel(location.ctf.id, location.category_channel.id)


async def start_challenge(
    guild: discord.Guild,
    ctf: Ctf,
    category: Category,
    channel: discord.TextChannel,
    user: discord.Member,
    slug: str,
) -> Started:
    """Adds `user` to the challenge's thread. When the challenge has no thread yet, or its thread was deleted by hand, a
    new public thread is created in `channel` (named `✅ <slug>` when the challenge is solved), stored, and added to the
    CTF's overview. An archived thread is unarchived first."""
    async with _lock:
        stored = store.challenge(ctf.id, category.slug, slug)
        thread = (
            None
            if stored is None
            else cast(discord.Thread | None, await discord_objects.thread(guild, stored.thread_id))
        )
        created = thread is None
        if thread is None:
            thread = await _create_thread(channel, user, slug, solved=stored is not None and stored.solved)
            store.add_challenge(ctf.id, category.slug, slug, thread.id)

    if thread.archived:
        await thread.edit(archived=False)
    await thread.add_user(user)
    if created:
        await overview.update(guild, ctf.id)
    return Started(thread, slug, created)


async def mark_solved(
    guild: discord.Guild, ctf: Ctf, thread: discord.Thread, challenge: Challenge, solved: bool
) -> bool:
    """Renames the thread to `✅ <slug>` or back to `<slug>` (unarchiving it if needed) and updates the overview.
    Returns False, changing nothing, when the challenge already had this state. When the thread can't be renamed, the
    stored state is reverted and the error is raised."""
    if not store.set_solved(ctf.id, challenge.category, challenge.slug, solved):
        return False
    try:
        await thread.edit(name=thread_name(challenge.slug, solved), archived=False)
    except discord.DiscordException:
        store.set_solved(ctf.id, challenge.category, challenge.slug, not solved)
        raise

    await overview.update(guild, ctf.id)
    return True


def thread_name(slug: str, solved: bool) -> str:
    return f"✅ {slug}" if solved else slug


async def _create_thread(channel: discord.TextChannel, user: discord.Member, slug: str, solved: bool) -> discord.Thread:
    """Deletes the starter message again when the thread can't be created, and raises the error."""
    message = await channel.send(
        f"🧩 `{slug}`, started by {user.mention}", allowed_mentions=discord.AllowedMentions.none()
    )
    try:
        return await message.create_thread(name=thread_name(slug, solved), auto_archive_duration=_AUTO_ARCHIVE)
    except discord.DiscordException:
        await message.delete()
        raise
