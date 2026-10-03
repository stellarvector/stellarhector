"""The challenge overview of a CTF: one message pinned in its main channel linking every challenge thread, grouped by
category, kept up to date by the bot."""
import asyncio
import logging

import discord

from utils import ctfs

# Discord refuses messages longer than this
MESSAGE_LIMIT = 2000

TITLE = "**Challenges**"

# Two updates at the same time could both find the overview missing and post it twice
_lock = asyncio.Lock()


def text(categories, challenges, limit=MESSAGE_LIMIT):
    """The overview of the challenges (sorted by category), under a header per category: its channel from categories, or
    its slug when it has none. A thread mention shows the thread's name, so `✅ <slug>` once solved.

    When it doesn't fit in limit characters, the last challenges are left out and a last line says how many.
    """
    channel_ids = {category.slug: category.channel_id for category in categories}
    lines = [TITLE]
    for index, challenge in enumerate(challenges):
        new = [f"<#{challenge.thread_id}>"]
        if index == 0 or challenge.category != challenges[index - 1].category:
            header = (f"<#{channel_ids[challenge.category]}>" if challenge.category in channel_ids
                      else f"**{challenge.category}**")
            new = ["", header] + new

        # Unless this is the last one, keep room to say the rest is left out
        left = len(challenges) - index - 1
        if len("\n".join(lines + new + _more(left))) > limit:
            return "\n".join(lines + _more(left + 1))
        lines += new
    return "\n".join(lines)


def _more(count):
    return ["", f"… and {count} more"] if count else []


async def update(guild, ctf_id):
    """Post the CTF's overview in its main channel and pin it, or edit it when it was posted already (pinning it again
    when it is not). Nothing is posted while the CTF has no challenges, nor when the CTF or its main channel was
    deleted. An overview deleted by hand is posted and pinned again.

    The overview is a side matter of the commands that update it, so a failing Discord call is logged, not raised.
    """
    async with _lock:
        ctf = ctfs.get(ctf_id)
        challenges = [] if ctf is None else ctfs.challenges(ctf.id)
        channel = None if ctf is None else guild.get_channel(ctf.main_channel_id)
        if not challenges or channel is None:
            return

        try:
            await _post_or_edit(channel, ctf, text(ctfs.categories(ctf.id), challenges))
        except discord.DiscordException as error:
            logging.getLogger("bot").error(f"Updating the challenge overview of {ctf.name} failed: {error}")


async def _post_or_edit(channel, ctf, content):
    message = None
    if ctf.overview_message_id is not None:
        try:
            message = await channel.get_partial_message(ctf.overview_message_id).edit(content=content)
        except discord.NotFound:
            pass

    if message is None:
        message = await channel.send(content, allowed_mentions=discord.AllowedMentions.none())
        ctfs.set_overview_message(ctf.id, message.id)
    if not message.pinned:
        await message.pin()
