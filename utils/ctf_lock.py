"""Locking a CTF once discussion has died down: it becomes read-only for everyone but the staff, its threads are
archived and locked, and it is archived to git right away. It stays readable until it is removed by hand."""
import logging
from dataclasses import dataclass

import discord

from utils import ctf_places, ctf_release, ctfs, discord_objects

# Taken from everyone but the writers, in the category and every channel synced to it, threads included
_WRITING = ("send_messages", "send_messages_in_threads", "create_public_threads", "create_private_threads",
            "add_reactions")


class LockRefused(Exception):
    """The CTF was not locked, and nothing changed; the message says why, for the user."""


@dataclass(frozen=True)
class LockRoles:
    """The names of the server's member role, and of the staff roles that keep writing in a locked CTF."""
    member: str | None
    writers: frozenset[str]


@dataclass(frozen=True)
class Locked:
    """A locked CTF as stored then, and why archiving it failed (None when it was archived)."""
    ctf: ctfs.Ctf
    archive_error: Exception | None

    @property
    def notice(self):
        """What to tell the staff in the CTF's #bot."""
        if self.archive_error is None:
            return "Locked and archived. Remove it with `/remove-ctf` when you're ready."
        error = f"{type(self.archive_error).__name__}: {self.archive_error}"
        return f":warning: Locked, but archiving failed: `{error}`\nRun `/archive-ctf` to try again."


async def lock(guild, ctf, roles, now, archive):
    """Release the CTF when it was not yet (ctf_release.release), make it read-only for everyone but roles.writers,
    archive and lock all of its threads, record now as its lock time and then archive it with
    archive(guild, ctf, now). Returns Locked.

    A failing archive is logged and returned, and the lock stays: the archive can be made with /archive-ctf. Raises
    LockRefused when the CTF was locked already (also by a run at the same time), or its category or the member role
    does not exist.
    """
    name = discord.utils.escape_markdown(ctf.name)
    # As stored now: it may have been released or locked since ctf was read
    stored = ctfs.get(ctf.id)
    if stored.locked_at is not None:
        raise _already_locked(name, stored)

    category = guild.get_channel(ctf.category_id)
    if category is None:
        raise LockRefused(f"The category of **{name}** no longer exists.")
    member_role = None if roles.member is None else discord.utils.get(guild.roles, name=roles.member)
    if member_role is None:
        raise LockRefused("The member role is not configured or no longer exists.")

    if stored.released_at is None:
        try:
            await ctf_release.release(guild, ctf, roles.member, now)
        except ctf_release.ReleaseRefused as e:
            raise LockRefused(str(e)) from e

        # The cached category only follows the release's edit once Discord tells the bot; building on it before
        # would hide the CTF from the members again
        category = await guild.fetch_channel(ctf.category_id)

    # A CTF role deleted by hand is skipped
    readers = [role for role in (guild.default_role, member_role, guild.get_role(ctf.role_id)) if role is not None]
    writers = [role for role in guild.roles if role.name in roles.writers]
    # Writers are allowed explicitly: an allow on one of a member's roles wins over a deny on another, and staff are
    # members too
    await ctf_places.update_category_overwrites(ctf, category, {
        **{role: dict.fromkeys(_WRITING, False) for role in readers},
        **{role: dict.fromkeys(_WRITING, True) for role in writers}})
    for channel in ctf_places.without_bot_channel(ctf, category.channels):
        for thread in await discord_objects.all_threads(channel):
            await _archive_and_lock(thread)
    if not ctfs.mark_locked(ctf.id, now):
        raise _already_locked(name, ctfs.get(ctf.id))
    logging.getLogger("bot").info(f"Locked CTF {ctf.name!r}")

    try:
        await archive(guild, ctf, now)
    except Exception as e:
        logging.getLogger("bot").exception(f"Could not archive the locked CTF {ctf.name!r}")
        return Locked(ctfs.get(ctf.id), e)
    return Locked(ctfs.get(ctf.id), None)


async def _archive_and_lock(thread):
    """Archive and lock thread, so it can't be reopened by posting in it. Discord only changes an archived thread
    when it is unarchived in the same request, so that one is unarchived and locked first."""
    if thread.archived:
        await thread.edit(archived=False, locked=True)
    await thread.edit(archived=True, locked=True)


def _already_locked(name, ctf):
    message = f"**{name}** was already locked <t:{int(ctf.locked_at.timestamp())}:R>, nothing changed."
    if ctf.archived_at is None:
        message += " It was not archived: run `/archive-ctf` to archive it."
    return LockRefused(message)
