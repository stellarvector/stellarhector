"""Releasing a CTF once it is over: every member can read and write in it (except its #bot, which stays staff only), and
joining closes."""
import logging

import discord

from utils import ctf_join, ctf_places, ctfs


class ReleaseRefused(Exception):
    """The CTF was not released, and nothing changed; the message says why, for the user."""


async def release(guild, ctf, member_role_name, now):
    """Open the CTF to the role named member_role_name (the server's members), close joining it (ctf_join.close_joining)
    and record now as its release time. Returns the CTF as stored then.

    The category's other overwrites are kept, and every channel but #bot is synced to it. Raises ReleaseRefused when
    the CTF was released already (also by a run at the same time), or its category or the member role does not exist.
    """
    name = discord.utils.escape_markdown(ctf.name)
    # As stored now: it may have been released since ctf was read
    stored = ctfs.get(ctf.id)
    if stored.released_at is not None:
        raise _already_released(name, stored)

    category = guild.get_channel(ctf.category_id)
    if category is None:
        raise ReleaseRefused(f"The category of **{name}** no longer exists.")
    member_role = None if member_role_name is None else discord.utils.get(guild.roles, name=member_role_name)
    if member_role is None:
        raise ReleaseRefused("The member role is not configured or no longer exists.")

    await _open_to(category, member_role, ctf)
    if not ctfs.mark_released(ctf.id, now):
        raise _already_released(name, ctfs.get(ctf.id))
    await ctf_join.close_joining(guild, ctf)

    logging.getLogger("bot").info(f"Released CTF {ctf.name!r}")
    return ctfs.get(ctf.id)


async def _open_to(category, role, ctf):
    """Let role see the category, keeping its other overwrites, and sync every channel in it but #bot to it. Writing
    is not denied, so role writes as it does elsewhere on the server; public threads follow their channel."""
    overwrites = dict(category.overwrites)
    overwrite = discord.PermissionOverwrite(**dict(overwrites.get(role, discord.PermissionOverwrite())))
    overwrite.update(view_channel=True)
    overwrites[role] = overwrite
    await category.edit(overwrites=overwrites)

    for channel in ctf_places.without_bot_channel(ctf, category.channels):
        await channel.edit(sync_permissions=True)


def _already_released(name, ctf):
    return ReleaseRefused(f"**{name}** was already released <t:{int(ctf.released_at.timestamp())}:R>, nothing "
                          f"changed.")
