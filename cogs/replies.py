"""Replies that several commands share."""

import asyncio
import logging
from collections.abc import Awaitable
from datetime import timedelta
from typing import TypeVar, cast

import discord

from ctf.location import Location, Place, locate
from ctf.models import Ctf
from feeds import FeedError
from utils.text import ERROR_LIMIT, inline_code

log = logging.getLogger("bot")

LOCKED = "This CTF is locked: it is read-only now, nothing can be added or changed."

PLACE_NAMES = {
    Place.MAIN: "the main channel",
    Place.BOT: "the #bot channel",
    Place.CATEGORY: "a category channel",
    Place.CHALLENGE: "a challenge thread",
}

T = TypeVar("T")


def guild(interaction: discord.Interaction) -> discord.Guild:
    """The server; the bot's commands and buttons only exist there."""
    return cast(discord.Guild, interaction.guild)


def member(interaction: discord.Interaction) -> discord.Member:
    """Who ran the command, as a member of the server."""
    return cast(discord.Member, interaction.user)


async def refuse(interaction: discord.Interaction, reason: str) -> None:
    """Tell only the user why the command doesn't run. Call it before responding."""
    await interaction.response.send_message(f":no_entry: {reason}", ephemeral=True)


def wrong_place(location: Location, *allowed: Place) -> str | None:
    """Where to run the command instead, or None when `location` is one of the allowed places."""
    if location.place in allowed:
        return None

    names = [PLACE_NAMES[place] for place in allowed]
    where = names[0] if len(names) == 1 else f"{', '.join(names[:-1])} or {names[-1]}"
    message = f"Run this in {where} of {'a' if location.ctf is None else 'the'} CTF"

    if location.ctf is not None and allowed == (Place.MAIN,):
        message += f": <#{location.ctf.main_channel_id}>"
    elif location.ctf is not None and allowed == (Place.BOT,):
        message += f": <#{location.ctf.bot_channel_id}>"
    return message


async def ctf_or_refuse(interaction: discord.Interaction, *allowed: Place) -> Ctf | None:
    """The CTF the command runs in, or None after telling the user where to run it instead."""
    location = locate(interaction.channel)
    message = wrong_place(location, *allowed)
    if message is not None:
        await refuse(interaction, message)
        return None
    assert location.ctf is not None
    return location.ctf


async def reply_after_long_work(interaction: discord.Interaction, content: str) -> None:
    """Reply to a deferred command, or post in its channel when the work took longer than the interaction lives (15
    minutes), as a long archive can."""
    try:
        await interaction.edit_original_response(content=content)
    except discord.HTTPException:
        await cast(discord.abc.Messageable, interaction.channel).send(content)


async def run_now(interaction: discord.Interaction, work: Awaitable[T], timeout: timedelta, what: str) -> T | None:
    """Run a scheduled job's work for a command, e.g. /blog-check. Replies and returns None when the feed can't be
    read or the work takes longer than `timeout`; otherwise the caller replies with the result."""
    # Downloading a feed, and waiting for a scheduled run in progress, can take longer than Discord waits for a reply
    await interaction.response.defer(thinking=True, ephemeral=True)
    try:
        return await asyncio.wait_for(work, timeout=timeout.total_seconds())
    except FeedError as e:
        await interaction.edit_original_response(
            content=f":warning: The {what} was skipped, nothing changed: {inline_code(str(e), ERROR_LIMIT)}"
        )
    except TimeoutError:
        log.error(f"The {what} command timed out")
        await interaction.edit_original_response(
            content=f":warning: The {what} took too long and was stopped. The next one carries on where it left off."
        )
    return None
