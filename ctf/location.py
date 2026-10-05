"""Which CTF a channel belongs to, and which place in that CTF it is. CTFs are found by their stored IDs, so renaming
channels by hand breaks nothing."""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum, auto
from typing import TypeVar, cast

import discord

from ctf import store
from ctf.models import Ctf

# What an interaction can be run in
Channel = discord.abc.GuildChannel | discord.Thread | discord.abc.PrivateChannel


class Place(Enum):
    MAIN = auto()
    BOT = auto()
    CATEGORY = auto()
    CHALLENGE = auto()
    ELSEWHERE = auto()


@dataclass(frozen=True)
class Location:
    ctf: Ctf | None
    place: Place
    # The category channel itself, or the parent channel of a challenge thread
    category_channel: discord.TextChannel | None = None


def locate(channel: Channel | None) -> Location:
    """A channel in a CTF's category is its main channel, its #bot or a category channel. A thread in a category
    channel is a challenge thread. Anything else, including a thread in the main channel or #bot, is ELSEWHERE."""
    parent = getattr(channel, "parent", None)
    container = parent or channel
    category_id = getattr(container, "category_id", None)
    ctf = None if category_id is None else store.find_by_category(category_id)
    if ctf is None or container is None:
        return Location(None, Place.ELSEWHERE)

    if container.id in (ctf.main_channel_id, ctf.bot_channel_id):
        if parent is not None:
            return Location(ctf, Place.ELSEWHERE)
        return Location(ctf, Place.MAIN if container.id == ctf.main_channel_id else Place.BOT)

    category_channel = cast(discord.TextChannel, container)
    return Location(ctf, Place.CHALLENGE if parent is not None else Place.CATEGORY, category_channel)


ChannelT = TypeVar("ChannelT", bound=discord.abc.Snowflake)


def without_bot_channel(ctf: Ctf, channels: Iterable[ChannelT]) -> list[ChannelT]:
    # #bot is for staff, not part of the CTF's content
    return [channel for channel in channels if channel.id != ctf.bot_channel_id]


def is_player_or_staff(member: discord.Member, ctf: Ctf, staff_roles: frozenset[str]) -> bool:
    return any(role.id == ctf.role_id or role.name in staff_roles for role in member.roles)
