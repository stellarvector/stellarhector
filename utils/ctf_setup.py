import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

import discord

from utils import ctf_join, ctfs, ctftime, discord_objects

# The guide posted as the first message in a CTF's main channel; change the text there, not here
GUIDE = (Path(__file__).parent / "templates" / "ctf_guide.md").read_text()

BOT_CHANNEL_NAME = "bot"

_HIDDEN = discord.PermissionOverwrite(view_channel=False)
_VISIBLE = discord.PermissionOverwrite(view_channel=True)
# The bot itself, so it can post and pin in the CTF's channels even without Administrator
_BOT = discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_messages=True)

# Two setups at the same time could both pass the duplicate check
_lock = asyncio.Lock()


@dataclass(frozen=True)
class Settings:
    """Names of the server's roles (None when not configured, then left out), the color of a CTF role, and the ID of
    #upcoming-ctfs for the join message (None when not configured, then no join message is posted)."""
    admin_role: str | None
    manager_role: str | None
    moderator_role: str | None
    member_role: str | None
    role_color: int
    upcoming_channel_id: int | None = None


class SetupRefused(Exception):
    """The CTF was not set up, and nothing was created; the message says why, for the user."""


async def setup_ctf(guild, name, ctftime_id, settings, get_event=ctftime.get_event):
    """Create the role, category, main channel (with the pinned guide and its Leave button) and #bot channel of a new
    CTF, store it, and post its join message in #upcoming-ctfs.

    With a ctftime_id, its start and finish are taken from CTFtime; the name stays as given. Returns the stored
    ctfs.Ctf. Raises SetupRefused when a CTF with this name or CTFtime ID already exists, or CTFtime does not know the
    event or can't be reached. When a Discord call fails, what was created is deleted again and the error is raised.
    """
    async with _lock:
        _refuse_duplicate(name, ctftime_id)
        event = None if ctftime_id is None else await _event(ctftime_id, get_event)

        created = []
        ctf = None
        try:
            new_ctf, guide = await _create_discord_objects(guild, name, settings, created)
            ctf = ctfs.create(ctfs.NewCtf(
                name=name, ctftime_id=ctftime_id, start=event and event.start, finish=event and event.finish,
                **new_ctf))
            # The buttons need the CTF's ID, so they come once it is stored
            await guide.edit(view=ctf_join.leave_view(ctf.id))
            ctf = await _post_join_message(guild, ctf, settings.upcoming_channel_id, created)
        except BaseException:
            logging.getLogger("bot").exception(f"Setting up CTF {name!r} failed, removing what was created")
            await discord_objects.delete_all(reversed(created), "of a failed CTF setup, delete it by hand")
            if ctf is not None:
                ctfs.delete(ctf.id)
            raise

    logging.getLogger("bot").info(f"Set up CTF {name!r} (CTFtime ID {ctftime_id})")
    return ctf


def _refuse_duplicate(name, ctftime_id):
    existing = ctfs.find(name=name, ctftime_id=ctftime_id)
    if existing is None:
        return

    same = "name" if existing.name.casefold() == name.casefold() else f"CTFtime ID {ctftime_id}"
    raise SetupRefused(f"A CTF with this {same} already exists: <#{existing.main_channel_id}>")


async def _event(ctftime_id, get_event):
    try:
        event = await get_event(ctftime_id)
    except ctftime.CtftimeError as e:
        logging.getLogger("bot").warning(f"Could not fetch CTFtime event {ctftime_id} to set up a CTF: {e}")
        raise SetupRefused(f"CTFtime could not be reached to look up event {ctftime_id}, try again later.") from e

    if event is None:
        raise SetupRefused(f"CTFtime does not know event {ctftime_id}.")
    return event


async def _create_discord_objects(guild, name, settings, created):
    """Create the CTF's Discord objects, appending each one to created as soon as it exists. Returns their IDs, and the
    guide message."""
    def role(role_name):
        return None if role_name is None else discord.utils.get(guild.roles, name=role_name)

    member, admin = role(settings.member_role), role(settings.admin_role)
    staff = [r for r in (admin, role(settings.manager_role), role(settings.moderator_role)) if r is not None]

    ctf_role = await guild.create_role(name=f"⚡ {name}", color=discord.Color(settings.role_color), mentionable=True)
    created.append(ctf_role)
    if member is not None:
        await ctf_role.edit(position=member.position + 1)

    hidden_for_everyone = {r: _HIDDEN for r in (guild.default_role, member) if r is not None}
    category_overwrites = {**hidden_for_everyone, ctf_role: _VISIBLE, **{r: _VISIBLE for r in staff}, guild.me: _BOT}
    if admin is not None:
        category_overwrites[admin] = discord.PermissionOverwrite(view_channel=True, manage_channels=True)
    category = await guild.create_category(f"⚡ {name}", overwrites=category_overwrites)
    created.append(category)

    # Discord shows a channel as synced when its overwrites are the category's. Without overwrites, discord.py would
    # create it with none at all, visible to everyone.
    main_channel = await guild.create_text_channel(name, category=category, overwrites=category_overwrites, position=0)
    created.append(main_channel)

    bot_channel = await guild.create_text_channel(
        BOT_CHANNEL_NAME, category=category,
        overwrites={**hidden_for_everyone, ctf_role: _HIDDEN, **{r: _VISIBLE for r in staff}, guild.me: _BOT})
    created.append(bot_channel)

    guide = await main_channel.send(GUIDE, allowed_mentions=discord.AllowedMentions.none())
    await guide.pin()

    return dict(role_id=ctf_role.id, category_id=category.id, main_channel_id=main_channel.id,
                bot_channel_id=bot_channel.id, guide_message_id=guide.id), guide


async def _post_join_message(guild, ctf, channel_id, created):
    """Post the CTF's join message in the channel with channel_id, appending it to created, and store where it is.
    Returns the CTF as stored then. Without the channel, no join message is posted."""
    channel = None if channel_id is None else guild.get_channel(channel_id)
    if channel is None:
        if channel_id is not None:
            logging.getLogger("bot").warning(f"#upcoming-ctfs ({channel_id}) does not exist, no join message for "
                                             f"CTF {ctf.name!r}")
        return ctf

    message = await channel.send(ctf_join.current_join_message(ctf), view=ctf_join.join_view(ctf.id),
                                 allowed_mentions=discord.AllowedMentions.none())
    created.append(message)
    ctfs.set_join_message(ctf.id, channel.id, message.id)
    return ctfs.get(ctf.id)
