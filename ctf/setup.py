"""Setting up a CTF: its role, its category with the main channel and #bot, and its join message."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import discord

from core.settings import Settings
from ctf import store
from ctf.buttons import join_view, leave_view
from ctf.join_message import current_join_message
from ctf.models import Ctf, NewCtf
from feeds import ctftime
from utils import discord_objects

log = logging.getLogger("bot")

# Posted and pinned as the first message of the main channel
GUIDE = (Path(__file__).parent / "guide.md").read_text()

BOT_CHANNEL_NAME = "bot"

_HIDDEN = discord.PermissionOverwrite(view_channel=False)
_VISIBLE = discord.PermissionOverwrite(view_channel=True)
# So the bot can post and pin in the CTF's channels even without Administrator
_BOT = discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_messages=True)

# Two setups at the same time could both pass the duplicate check
_lock = asyncio.Lock()

GetEvent = Callable[[int], Awaitable[ctftime.Event | None]]
Overwrites = dict[discord.Role | discord.Member | discord.Object, discord.PermissionOverwrite]
# Everything the setup created on Discord, in order, so a failed setup can delete it again
Created = list[discord.Role | discord.abc.GuildChannel | discord.Message]


class SetupRefused(Exception):
    """Nothing was created; the message tells the user why."""


@dataclass(frozen=True)
class _DiscordObjects:
    role_id: int
    category_id: int
    main_channel_id: int
    bot_channel_id: int
    guide: discord.Message


async def setup_ctf(
    guild: discord.Guild,
    name: str,
    ctftime_id: int | None,
    settings: Settings,
    get_event: GetEvent = ctftime.get_event,
) -> Ctf:
    """Create the CTF on Discord, store it and post its join message. With a CTFtime ID, the dates come from CTFtime.

    Refused when a CTF with this name or CTFtime ID exists, or CTFtime doesn't know the event. When Discord fails
    halfway, everything created so far is deleted again.
    """
    async with _lock:
        _refuse_duplicate(name, ctftime_id)
        event = None if ctftime_id is None else await _event(ctftime_id, get_event)

        created: Created = []
        ctf = None
        try:
            objects = await _create_discord_objects(guild, name, settings, created)
            ctf = store.create(
                NewCtf(
                    name=name,
                    ctftime_id=ctftime_id,
                    start=None if event is None else event.start,
                    finish=None if event is None else event.finish,
                    role_id=objects.role_id,
                    category_id=objects.category_id,
                    main_channel_id=objects.main_channel_id,
                    bot_channel_id=objects.bot_channel_id,
                    guide_message_id=objects.guide.id,
                )
            )
            # The button needs the CTF's ID, which it has once stored
            await objects.guide.edit(view=leave_view(ctf.id))
            ctf = await _post_join_message(guild, ctf, settings.channels.upcoming_ctfs, created)
        except BaseException:
            log.exception(f"Setting up CTF {name!r} failed, removing what was created")
            await discord_objects.delete_all(reversed(created), "of a failed CTF setup, delete it by hand")
            if ctf is not None:
                store.delete(ctf.id)
            raise

    log.info(f"Set up CTF {name!r} (CTFtime ID {ctftime_id})")
    return ctf


def _refuse_duplicate(name: str, ctftime_id: int | None) -> None:
    existing = store.find(name=name, ctftime_id=ctftime_id)
    if existing is None:
        return

    same = "name" if existing.name.casefold() == name.casefold() else f"CTFtime ID {ctftime_id}"
    raise SetupRefused(f"A CTF with this {same} already exists: <#{existing.main_channel_id}>")


async def _event(ctftime_id: int, get_event: GetEvent) -> ctftime.Event:
    try:
        event = await get_event(ctftime_id)
    except ctftime.CtftimeError as e:
        log.warning(f"Could not fetch CTFtime event {ctftime_id} to set up a CTF: {e}")
        raise SetupRefused(f"CTFtime could not be reached to look up event {ctftime_id}, try again later.") from e

    if event is None:
        raise SetupRefused(f"CTFtime does not know event {ctftime_id}.")
    return event


async def _create_discord_objects(
    guild: discord.Guild, name: str, settings: Settings, created: Created
) -> _DiscordObjects:
    """Each object is added to `created` as soon as it exists."""

    def role(role_name: str | None) -> discord.Role | None:
        return None if role_name is None else discord.utils.get(guild.roles, name=role_name)

    roles = settings.roles
    member, admin = role(roles.member), role(roles.admin)
    staff = [r for r in (admin, role(roles.manager), role(roles.moderator)) if r is not None]

    ctf_role = await guild.create_role(
        name=f"⚡ {name}", color=discord.Color(settings.ctf_role_color), mentionable=True
    )
    created.append(ctf_role)
    if member is not None:
        await ctf_role.edit(position=member.position + 1)

    hidden_for_everyone: Overwrites = {r: _HIDDEN for r in (guild.default_role, member) if r is not None}
    category_overwrites: Overwrites = {
        **hidden_for_everyone,
        ctf_role: _VISIBLE,
        **{r: _VISIBLE for r in staff},
        guild.me: _BOT,
    }
    if admin is not None:
        category_overwrites[admin] = discord.PermissionOverwrite(view_channel=True, manage_channels=True)
    category = await guild.create_category(f"⚡ {name}", overwrites=category_overwrites)
    created.append(category)

    # Discord shows a channel as synced when its overwrites are the category's. Without overwrites, discord.py would
    # create it without any, visible to everyone.
    main_channel = await guild.create_text_channel(name, category=category, overwrites=category_overwrites, position=0)
    created.append(main_channel)

    bot_overwrites: Overwrites = {
        **hidden_for_everyone,
        ctf_role: _HIDDEN,
        **{r: _VISIBLE for r in staff},
        guild.me: _BOT,
    }
    bot_channel = await guild.create_text_channel(
        BOT_CHANNEL_NAME,
        category=category,
        overwrites=bot_overwrites,
    )
    created.append(bot_channel)

    guide = await main_channel.send(GUIDE, allowed_mentions=discord.AllowedMentions.none())
    await guide.pin()

    return _DiscordObjects(ctf_role.id, category.id, main_channel.id, bot_channel.id, guide)


async def _post_join_message(guild: discord.Guild, ctf: Ctf, channel_id: int | None, created: Created) -> Ctf:
    """Without #upcoming-ctfs, no join message is posted."""
    channel = None if channel_id is None else cast(discord.TextChannel | None, guild.get_channel(channel_id))
    if channel is None:
        if channel_id is not None:
            log.warning(f"#upcoming-ctfs ({channel_id}) does not exist, no join message for CTF {ctf.name!r}")
        return ctf

    message = await channel.send(
        current_join_message(ctf), view=join_view(ctf.id), allowed_mentions=discord.AllowedMentions.none()
    )
    created.append(message)
    store.set_join_message(ctf.id, channel.id, message.id)
    return store.reread(ctf.id)
