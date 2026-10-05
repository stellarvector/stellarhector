import logging
from collections.abc import Mapping
from typing import cast

import discord

from core.settings import Roles
from ctf.location import without_bot_channel
from ctf.models import Ctf

log = logging.getLogger("bot")

# Per role: permission name -> allowed (True), denied (False) or inherited (None)
PermissionChanges = Mapping[discord.Role, Mapping[str, bool | None]]


async def update_category_overwrites(ctf: Ctf, category: discord.CategoryChannel, changes: PermissionChanges) -> None:
    """Apply the changes to the CTF category's overwrites, keeping all other overwrites, and sync every channel in the
    category except #bot to it."""
    overwrites = dict(category.overwrites)
    for role, permissions in changes.items():
        overwrite = discord.PermissionOverwrite(**dict(overwrites.get(role, discord.PermissionOverwrite())))
        overwrite.update(**permissions)
        overwrites[role] = overwrite
    await category.edit(overwrites=overwrites)

    # A category holds no categories, so every channel in it can sync
    for channel in without_bot_channel(ctf, category.channels):
        await cast(discord.TextChannel, channel).edit(sync_permissions=True)


def member_roles(guild: discord.Guild, roles: Roles) -> list[discord.Role]:
    """The server's roles of the team's members (players and followers). A configured role that the server doesn't
    have is left out with a warning."""
    found = []
    for name in sorted(roles.members):
        role = discord.utils.get(guild.roles, name=name)
        if role is None:
            log.warning(f"The role {name!r} is configured but doesn't exist on the server")
        else:
            found.append(role)
    return found
