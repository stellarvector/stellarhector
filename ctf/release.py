"""Releasing a CTF once it is over: every member can read and write in it (except #bot, which stays staff only), and
joining closes."""

import logging
from datetime import datetime
from typing import cast

import discord

from core.settings import Roles
from ctf import store
from ctf.joining import close_joining
from ctf.models import Ctf
from ctf.permissions import member_roles, update_category_overwrites
from utils.text import discord_time

log = logging.getLogger("bot")


NO_MEMBER_ROLES = "Neither the player nor the follower role is configured and on the server."
RELEASED_MESSAGE = "🔓 This CTF is now open to all members. Welcome!"


class ReleaseRefused(Exception):
    """Nothing changed; the message tells the user why."""


async def release_ctf(guild: discord.Guild, ctf: Ctf, roles: Roles, now: datetime, announce: bool = True) -> Ctf:
    """Open the CTF to the members and close joining. With `announce`, the members are welcomed in its main channel."""
    name = discord.utils.escape_markdown(ctf.name)
    # Re-read: it may have been released since `ctf` was read
    if (stored := store.reread(ctf.id)).released_at is not None:
        raise _already_released(name, stored)

    category = cast(discord.CategoryChannel | None, guild.get_channel(ctf.category_id))
    if category is None:
        raise ReleaseRefused(f"The category of **{name}** no longer exists.")
    members = member_roles(guild, roles)
    if not members:
        raise ReleaseRefused(NO_MEMBER_ROLES)

    # Sending is not denied, so members write as they do elsewhere on the server; public threads follow their channel
    await update_category_overwrites(ctf, category, {role: {"view_channel": True} for role in members})
    # A command and the timeline releasing at the same time: only one gets here
    if not store.mark_released(ctf.id, now):
        raise _already_released(name, store.reread(ctf.id))
    await close_joining(guild, ctf)
    if announce:
        await announce_in_main_channel(guild, ctf, RELEASED_MESSAGE)

    log.info(f"Released CTF {ctf.name!r}")
    return store.reread(ctf.id)


async def announce_in_main_channel(guild: discord.Guild, ctf: Ctf, message: str) -> None:
    """Post `message` in the CTF's main channel. The step it announces is done, so a failure is only logged."""
    channel = cast(discord.TextChannel | None, guild.get_channel(ctf.main_channel_id))
    if channel is None:
        log.warning(f"The main channel of CTF {ctf.name!r} no longer exists, not announced: {message}")
        return
    try:
        await channel.send(message, allowed_mentions=discord.AllowedMentions.none())
    except discord.HTTPException:
        log.exception(f"Could not announce in the main channel of CTF {ctf.name!r}: {message}")


def _already_released(name: str, ctf: Ctf) -> ReleaseRefused:
    assert ctf.released_at is not None
    return ReleaseRefused(f"**{name}** was already released {discord_time(ctf.released_at, 'R')}, nothing changed.")
