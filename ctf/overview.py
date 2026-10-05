"""The challenge overview of a CTF: one message pinned in its main channel linking every challenge thread, grouped by
category, kept up to date by the bot."""

import asyncio
import logging
from collections.abc import Sequence
from typing import cast

import discord

from ctf import store
from ctf.models import Category, Challenge, Ctf

log = logging.getLogger("bot")

# Discord refuses messages longer than this
MESSAGE_LIMIT = 2000

TITLE = "**Challenges**"

# Two concurrent updates could both find the overview missing and post it twice
_lock = asyncio.Lock()


def text(categories: Sequence[Category], challenges: Sequence[Challenge], limit: int = MESSAGE_LIMIT) -> str:
    """Lists the `challenges`, which must be sorted by category, under a header per category: the category's channel,
    or its slug when it has none in `categories`. Discord renders a thread mention as the thread's name, so solved
    challenges show as `✅ <slug>`.

    When the text doesn't fit in `limit` characters, the last challenges are left out and a final line says how many.
    """
    channel_ids = {category.slug: category.channel_id for category in categories}
    lines = [TITLE]
    for index, challenge in enumerate(challenges):
        new = [f"<#{challenge.thread_id}>"]
        if index == 0 or challenge.category != challenges[index - 1].category:
            header = (
                f"<#{channel_ids[challenge.category]}>"
                if challenge.category in channel_ids
                else f"**{challenge.category}**"
            )
            new = ["", header] + new

        # Unless this is the last one, keep room to say the rest is left out
        left = len(challenges) - index - 1
        if len("\n".join(lines + new + _more(left))) > limit:
            return "\n".join(lines + _more(left + 1))
        lines += new
    return "\n".join(lines)


def _more(count: int) -> list[str]:
    return ["", f"… and {count} more"] if count else []


async def update(guild: discord.Guild, ctf_id: int) -> None:
    """Posts and pins the CTF's overview in its main channel, or edits it when it exists (pinning it again if it was
    unpinned). Nothing is posted while the CTF has no challenges, or when the CTF or its main channel is gone. An
    overview deleted by hand is posted again.

    The overview is secondary to the commands that update it, so a failing Discord call is logged, not raised.
    """
    async with _lock:
        ctf = store.get(ctf_id)
        if ctf is None:
            return
        challenges = store.challenges(ctf.id)
        channel = cast(discord.TextChannel | None, guild.get_channel(ctf.main_channel_id))
        if not challenges or channel is None:
            return

        try:
            await _post_or_edit(channel, ctf, text(store.categories(ctf.id), challenges))
        except discord.DiscordException as error:
            log.error(f"Updating the challenge overview of {ctf.name} failed: {error}")


async def _post_or_edit(channel: discord.TextChannel, ctf: Ctf, content: str) -> None:
    message = None
    if ctf.overview_message_id is not None:
        try:
            message = await channel.get_partial_message(ctf.overview_message_id).edit(content=content)
        except discord.NotFound:
            pass

    if message is None:
        message = await channel.send(content, allowed_mentions=discord.AllowedMentions.none())
        store.set_overview_message(ctf.id, message.id)
    if not message.pinned:
        await message.pin()
