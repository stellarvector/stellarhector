"""The challenge categories of a CTF (web, crypto, pwn, …): a channel each in the CTF's category, made with
/add-category."""

import asyncio
from dataclasses import dataclass, field
from typing import cast

import discord

from archive.naming import normalize_name
from ctf import store
from ctf.models import Category, Ctf

# Two concurrent runs could both find a category missing and make it twice
_lock = asyncio.Lock()


@dataclass(frozen=True)
class Added:
    created: list[discord.TextChannel] = field(default_factory=list)
    existing: list[Category] = field(default_factory=list)
    # Names, as typed, that are empty once turned into a slug
    invalid: list[str] = field(default_factory=list)


def slug(name: str) -> str:
    """Returns the category's channel name: lowercase, with spaces turned into dashes and everything except letters,
    digits and dashes removed. Returns an empty string when nothing is left."""
    return normalize_name(name, fallback="").lower()


def split_names(text: str) -> list[str]:
    return [name.strip() for name in text.split(",") if name.strip()]


async def add_categories(guild: discord.Guild, ctf: Ctf, text: str) -> Added:
    """Creates and stores a channel for each category in the comma-separated `text` that the CTF does not have yet,
    including stored categories whose channel was deleted by hand. The channels are synced to the CTF's category and
    sorted alphabetically below the main channel. Names that produce the same slug create a single channel.

    When a Discord call fails, the error is raised; the categories created before it are kept and sorted.
    """
    slugs, invalid = set(), []
    for name in split_names(text):
        if new := slug(name):
            slugs.add(new)
        else:
            invalid.append(name)

    created, existing = {}, []
    async with _lock:
        stored = {category.slug: category for category in store.categories(ctf.id)}
        category_channel = cast(discord.CategoryChannel, guild.get_channel(ctf.category_id))
        try:
            for new in sorted(slugs):
                if new in stored and guild.get_channel(stored[new].channel_id) is not None:
                    existing.append(stored[new])
                    continue

                # Discord shows a channel as synced when its overwrites are the category's
                created[new] = await guild.create_text_channel(
                    new, category=category_channel, overwrites=category_channel.overwrites
                )
                store.add_category(ctf.id, new, created[new].id)
        finally:
            if created:
                await _sort(guild, ctf, category_channel, created)

    return Added(created=list(created.values()), existing=existing, invalid=invalid)


async def _sort(
    guild: discord.Guild,
    ctf: Ctf,
    category_channel: discord.CategoryChannel,
    created: dict[str, discord.TextChannel],
) -> None:
    """Orders the CTF's category as: the main channel, then the category channels alphabetically, then the rest (#bot,
    …).

    `created` maps slugs to the channels just created, because the guild's cache may not contain them yet. A single
    request sets every position, since moving channels one by one would rely on cached positions that may be stale.
    """
    categories = {
        category.slug: created.get(category.slug) or guild.get_channel(category.channel_id)
        for category in store.categories(ctf.id)
    }
    wanted = [guild.get_channel(ctf.main_channel_id)] + [categories[s] for s in sorted(categories)]
    ordered = [channel for channel in wanted if channel is not None]
    ids = {channel.id for channel in ordered}
    ordered += [channel for channel in category_channel.text_channels if channel.id not in ids]

    # discord.py has no public way to set several positions at once; GuildChannel.move makes this same request
    await guild._state.http.bulk_channel_update(
        guild.id, [{"id": channel.id, "position": position} for position, channel in enumerate(ordered)]
    )
