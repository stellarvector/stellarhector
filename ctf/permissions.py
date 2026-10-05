from collections.abc import Mapping
from typing import cast

import discord

from ctf.location import without_bot_channel
from ctf.models import Ctf

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
