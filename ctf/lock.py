"""Locking a CTF once discussion has died down: it becomes read-only for everyone but the staff, its threads are
archived and locked, and it is archived to git. It stays readable until it is removed."""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import cast

import discord

from core.settings import Roles
from ctf import store
from ctf.location import without_bot_channel
from ctf.models import Ctf
from ctf.permissions import update_category_overwrites
from ctf.release import ReleaseRefused, release_ctf
from utils import discord_objects
from utils.text import discord_time

log = logging.getLogger("bot")

ArchiveCtf = Callable[[discord.Guild, Ctf, datetime], Awaitable[None]]

# Denied to everyone but the staff, in the category and every channel synced to it, threads included
_WRITING = (
    "send_messages",
    "send_messages_in_threads",
    "create_public_threads",
    "create_private_threads",
    "add_reactions",
)


class LockRefused(Exception):
    """Nothing changed; the message tells the user why."""


@dataclass(frozen=True)
class Locked:
    ctf: Ctf
    # Why archiving failed; None when the CTF was archived
    archive_error: Exception | None


async def lock_ctf(guild: discord.Guild, ctf: Ctf, roles: Roles, now: datetime, archive: ArchiveCtf) -> Locked:
    """Release the CTF if that hasn't happened yet, make it read-only for everyone but the staff, archive and lock its
    threads, then archive it with `archive`. A failing archive doesn't undo the lock: it is returned, so it can be
    retried with /archive-ctf."""
    name = discord.utils.escape_markdown(ctf.name)
    # Re-read: it may have been released or locked since `ctf` was read
    stored = store.reread(ctf.id)
    if stored.locked_at is not None:
        raise _already_locked(name, stored)

    category = cast(discord.CategoryChannel | None, guild.get_channel(ctf.category_id))
    if category is None:
        raise LockRefused(f"The category of **{name}** no longer exists.")
    member_role = None if roles.member is None else discord.utils.get(guild.roles, name=roles.member)
    if member_role is None:
        raise LockRefused("The member role is not configured or no longer exists.")

    if stored.released_at is None:
        try:
            await release_ctf(guild, ctf, roles.member, now)
        except ReleaseRefused as e:
            raise LockRefused(str(e)) from e
        # The cached category only reflects the release once Discord tells the bot about it; building on the cached
        # overwrites would hide the CTF from the members again
        category = cast(discord.CategoryChannel, await guild.fetch_channel(ctf.category_id))

    readers = [role for role in (guild.default_role, member_role, guild.get_role(ctf.role_id)) if role is not None]
    writers = [role for role in guild.roles if role.name in roles.staff]
    # Staff are allowed explicitly: they are members too, and an allow on one role wins over a deny on another
    await update_category_overwrites(
        ctf,
        category,
        {
            **{role: dict.fromkeys(_WRITING, False) for role in readers},
            **{role: dict.fromkeys(_WRITING, True) for role in writers},
        },
    )
    for channel in without_bot_channel(ctf, category.channels):
        for thread in await discord_objects.all_threads(channel):
            await _archive_and_lock(thread)
    if not store.mark_locked(ctf.id, now):
        raise _already_locked(name, store.reread(ctf.id))
    log.info(f"Locked CTF {ctf.name!r}")

    try:
        await archive(guild, ctf, now)
    except Exception as e:
        log.exception(f"Could not archive the locked CTF {ctf.name!r}")
        return Locked(store.reread(ctf.id), e)
    return Locked(store.reread(ctf.id), None)


async def _archive_and_lock(thread: discord.Thread) -> None:
    # Discord only edits an archived thread when the same request unarchives it
    if thread.archived:
        await thread.edit(archived=False, locked=True)
    await thread.edit(archived=True, locked=True)


def _already_locked(name: str, ctf: Ctf) -> LockRefused:
    assert ctf.locked_at is not None
    message = f"**{name}** was already locked {discord_time(ctf.locked_at, 'R')}, nothing changed."
    if ctf.archived_at is None:
        message += " It was not archived: run `/archive-ctf` to archive it."
    return LockRefused(message)
