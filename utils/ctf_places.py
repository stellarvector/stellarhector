from dataclasses import dataclass
from enum import Enum

from utils import ctfs


class Place(Enum):
    """Where in a CTF a command is run; the value names it for the user."""
    MAIN = "the main channel"
    BOT = "the #bot channel"
    CATEGORY = "a category channel"
    CHALLENGE = "a challenge thread"
    ELSEWHERE = "somewhere else"


@dataclass(frozen=True)
class Location:
    """The CTF a channel belongs to (None when it is in none), and what place in it the channel is.

    category_channel is the category channel itself, or the parent of a challenge thread, else None.
    """
    ctf: ctfs.Ctf | None
    place: Place
    category_channel: object = None


def locate(channel):
    """Where channel (a text channel or thread) is, found by the IDs stored for the CTFs, so names don't matter.

    A channel in a CTF's category is its main channel, its #bot or else a category channel; a thread in a category
    channel is a challenge thread. Anything else, also a thread in the main channel or #bot, is ELSEWHERE.
    """
    parent = getattr(channel, "parent", None)
    container = parent or channel
    category_id = getattr(container, "category_id", None)
    ctf = None if category_id is None else ctfs.find_by_category(category_id)
    if ctf is None:
        return Location(None, Place.ELSEWHERE)

    if container.id in (ctf.main_channel_id, ctf.bot_channel_id):
        if parent is not None:
            return Location(ctf, Place.ELSEWHERE)
        return Location(ctf, Place.MAIN if channel.id == ctf.main_channel_id else Place.BOT)

    return Location(ctf, Place.CHALLENGE if parent is not None else Place.CATEGORY, container)


def without_bot_channel(ctf, channels):
    """The channels, except the CTF's #bot: that is staff only, not CTF content."""
    return [channel for channel in channels if channel.id != ctf.bot_channel_id]


def wrong_place(location, *allowed):
    """None when location is one of the allowed places, else a message for the user naming where to run it."""
    if location.place in allowed:
        return None

    names = [place.value for place in allowed]
    where = names[0] if len(names) == 1 else f"{', '.join(names[:-1])} or {names[-1]}"
    message = f"Run this in {where} of {'a' if location.ctf is None else 'the'} CTF"

    if location.ctf is not None and allowed == (Place.MAIN,):
        message += f": <#{location.ctf.main_channel_id}>"
    elif location.ctf is not None and allowed == (Place.BOT,):
        message += f": <#{location.ctf.bot_channel_id}>"
    return message


async def locate_or_refuse(interaction, *allowed):
    """The Location of the interaction's channel when it is one of the allowed places.

    Otherwise it replies, only to the user, where to run the command, and returns None. Call it before responding.
    """
    location = locate(interaction.channel)
    message = wrong_place(location, *allowed)
    if message is None:
        return location

    await interaction.response.send_message(f":no_entry: {message}", ephemeral=True)
    return None
