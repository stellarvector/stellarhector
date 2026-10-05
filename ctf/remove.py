import logging
from dataclasses import dataclass
from datetime import datetime
from typing import cast

import discord

from ctf import store
from ctf.location import without_bot_channel
from ctf.models import Ctf
from utils import discord_objects

log = logging.getLogger("bot")


@dataclass(frozen=True)
class Removal:
    removed: bool
    # The names of the Discord objects that could not be deleted
    not_deleted: list[str]


async def remove_ctf(guild: discord.Guild, ctf: Ctf, now: datetime) -> Removal:
    """Delete the CTF's channels, role and category and record it as removed. #bot goes last: when something else can't
    be deleted, #bot and the stored CTF stay, so the command can be run again there."""
    category = cast(discord.CategoryChannel | None, guild.get_channel(ctf.category_id))
    content = [] if category is None else without_bot_channel(ctf, category.channels)
    not_deleted = await discord_objects.delete_all([*content, guild.get_role(ctf.role_id)], "of a removed CTF")
    if not_deleted:
        return Removal(removed=False, not_deleted=not_deleted)

    not_deleted = await discord_objects.delete_all(
        [guild.get_channel(ctf.bot_channel_id), category], "of a removed CTF"
    )
    store.mark_removed(ctf.id, now)
    log.info(f"Removed CTF {ctf.name!r}")
    return Removal(removed=True, not_deleted=not_deleted)
