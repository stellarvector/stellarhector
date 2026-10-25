"""The credentials of a CTF (a team account, a VPN config, …): posted and pinned in its main channel with
/post-credentials, and deleted again right before the CTF is released, so they never become public."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast

import discord

from ctf import store
from ctf.models import Ctf, Stage
from utils.text import error_code

log = logging.getLogger("bot")

HEADER = "🔑 **Credentials**\n"
# A message holds at most 2000 characters, the header included
TEXT_LIMIT = 1900

# A post running alongside another post or the release could leave a message that is not stored, and so not deleted
_lock = asyncio.Lock()


class CredentialsRefused(Exception):
    """Nothing was posted; the message tells the user why."""


async def post_credentials(guild: discord.Guild, ctf: Ctf, text: str) -> discord.Message:
    """Post and pin the credentials in the CTF's main channel, replacing earlier ones. Refused once the CTF is
    released, and when the earlier credentials can't be deleted."""
    name = discord.utils.escape_markdown(ctf.name)
    async with _lock:
        # Re-read: it may have been released since `ctf` was read
        stored = store.reread(ctf.id)
        if (reason := too_late(stored)) is not None:
            raise CredentialsRefused(reason)
        channel = _main_channel(guild, stored)
        if channel is None:
            raise CredentialsRefused(f"The main channel of **{name}** no longer exists.")

        await _delete(guild, stored, "earlier credentials")
        message = await channel.send(HEADER + text, allowed_mentions=discord.AllowedMentions.none())
        # Stored before pinning, so it is deleted at the release even when pinning fails
        store.set_credentials_message(ctf.id, message.id)
        await message.pin()

    log.info(f"Posted credentials in CTF {ctf.name!r}")
    return message


def too_late(ctf: Ctf) -> str | None:
    """Why no credentials can be posted in the CTF anymore, or None while they can."""
    if ctf.stage is Stage.SET_UP:
        return None
    name = discord.utils.escape_markdown(ctf.name)
    return f"**{name}** is {ctf.stage.value}: the credentials would be visible to all members."


async def current_credentials(guild: discord.Guild, ctf: Ctf) -> str | None:
    """The text of the CTF's credentials, without their header; None when there are none or they are gone."""
    channel = _main_channel(guild, ctf)
    if ctf.credentials_message_id is None or channel is None:
        return None
    try:
        message = await channel.fetch_message(ctf.credentials_message_id)
    except discord.HTTPException:
        return None
    return message.content.removeprefix(HEADER)


@asynccontextmanager
async def removed(guild: discord.Guild, ctf: Ctf) -> AsyncIterator[None]:
    """Delete the CTF's credentials, and post no new ones until the block ends: run the release in it. Credentials
    deleted by hand count as deleted; raises CredentialsRefused when Discord refuses."""
    async with _lock:
        await _delete(guild, store.reread(ctf.id), "credentials")
        yield


async def _delete(guild: discord.Guild, ctf: Ctf, which: str) -> None:
    if ctf.credentials_message_id is None:
        return
    channel = _main_channel(guild, ctf)
    if channel is not None:
        try:
            await channel.get_partial_message(ctf.credentials_message_id).delete()
        except discord.NotFound:
            pass
        except discord.HTTPException as e:
            raise CredentialsRefused(
                f"The {which} in <#{ctf.main_channel_id}> could not be deleted: {error_code(e)}\n"
                "Delete them by hand and try again."
            ) from e
    store.set_credentials_message(ctf.id, None)
    log.info(f"Deleted the credentials of CTF {ctf.name!r}")


def _main_channel(guild: discord.Guild, ctf: Ctf) -> discord.TextChannel | None:
    return cast(discord.TextChannel | None, guild.get_channel(ctf.main_channel_id))
