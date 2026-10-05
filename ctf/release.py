"""Releasing a CTF once it is over: every member can read and write in it (except #bot, which stays staff only), and
joining closes."""

import logging
from datetime import datetime
from typing import cast

import discord

from ctf import store
from ctf.joining import close_joining
from ctf.models import Ctf
from ctf.permissions import update_category_overwrites
from utils.text import discord_time

log = logging.getLogger("bot")


class ReleaseRefused(Exception):
    """Nothing changed; the message tells the user why."""


async def release_ctf(guild: discord.Guild, ctf: Ctf, member_role_name: str | None, now: datetime) -> Ctf:
    name = discord.utils.escape_markdown(ctf.name)
    # Re-read: it may have been released since `ctf` was read
    if (stored := store.reread(ctf.id)).released_at is not None:
        raise _already_released(name, stored)

    category = cast(discord.CategoryChannel | None, guild.get_channel(ctf.category_id))
    if category is None:
        raise ReleaseRefused(f"The category of **{name}** no longer exists.")
    member_role = None if member_role_name is None else discord.utils.get(guild.roles, name=member_role_name)
    if member_role is None:
        raise ReleaseRefused("The member role is not configured or no longer exists.")

    # Sending is not denied, so members write as they do elsewhere on the server; public threads follow their channel
    await update_category_overwrites(ctf, category, {member_role: {"view_channel": True}})
    # A command and the timeline releasing at the same time: only one gets here
    if not store.mark_released(ctf.id, now):
        raise _already_released(name, store.reread(ctf.id))
    await close_joining(guild, ctf)

    log.info(f"Released CTF {ctf.name!r}")
    return store.reread(ctf.id)


def _already_released(name: str, ctf: Ctf) -> ReleaseRefused:
    assert ctf.released_at is not None
    return ReleaseRefused(f"**{name}** was already released {discord_time(ctf.released_at, 'R')}, nothing changed.")
