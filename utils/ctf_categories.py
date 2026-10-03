"""The challenge categories of a CTF (web, crypto, pwn, …): a channel each in the CTF's category, made with
/add-category."""
import asyncio
from dataclasses import dataclass, field

import discord

from utils import ctfs
from utils.archive.naming import normalize_name

# Two runs at the same time could both find a category missing and make it twice
_lock = asyncio.Lock()


@dataclass(frozen=True)
class Added:
    """What add_categories did: the channels it created, the categories that existed already, and the names as typed
    that were skipped because nothing is left of them as a slug."""
    created: list[discord.TextChannel] = field(default_factory=list)
    existing: list[ctfs.Category] = field(default_factory=list)
    invalid: list[str] = field(default_factory=list)


def slug(name):
    """The category's channel name: lowercase, spaces become dashes, everything but letters, digits and dashes removed.
    Empty when nothing is left."""
    return normalize_name(name, fallback="").lower()


def split_names(text):
    """The names in the comma-separated text, trimmed, leaving out blank ones."""
    return [name.strip() for name in text.split(",") if name.strip()]


async def add_categories(guild, ctf, text):
    """Create a channel for each category named in the comma-separated text that the CTF does not have yet, and store
    it. A stored category whose channel was deleted by hand is created again. The channels go in the CTF's category,
    synced to it, in alphabetical order below the main channel.

    A name given more than once, also in ways that make the same slug, is made once. Returns what was Added. When a
    Discord call fails the error is raised; the categories made before it stay, in their place.
    """
    slugs, invalid = set(), []
    for name in split_names(text):
        if new := slug(name):
            slugs.add(new)
        else:
            invalid.append(name)

    created, existing = {}, []
    async with _lock:
        stored = {category.slug: category for category in ctfs.categories(ctf.id)}
        category_channel = guild.get_channel(ctf.category_id)
        try:
            for new in sorted(slugs):
                if new in stored and guild.get_channel(stored[new].channel_id) is not None:
                    existing.append(stored[new])
                    continue

                # Discord shows a channel as synced when its overwrites are the category's
                created[new] = await guild.create_text_channel(new, category=category_channel,
                                                               overwrites=category_channel.overwrites)
                ctfs.add_category(ctf.id, new, created[new].id)
        finally:
            if created:
                await _sort(guild, ctf, category_channel, created)

    return Added(created=list(created.values()), existing=existing, invalid=invalid)


async def _sort(guild, ctf, category_channel, created):
    """Put the CTF's main channel first in its category, then its categories alphabetically, then the rest (#bot, …).

    The channels just created, by slug, are given, because the guild may not know them yet. One request sets every
    position: moving them one by one would go by positions the guild may not have updated yet.
    """
    categories = {category.slug: created.get(category.slug) or guild.get_channel(category.channel_id)
                  for category in ctfs.categories(ctf.id)}
    ordered = [guild.get_channel(ctf.main_channel_id)] + [categories[s] for s in sorted(categories)]
    ordered = [channel for channel in ordered if channel is not None]
    ids = {channel.id for channel in ordered}
    ordered += [channel for channel in category_channel.text_channels if channel.id not in ids]

    # discord.py has no public way to set several positions at once; GuildChannel.move makes this same request
    await guild._state.http.bulk_channel_update(
        guild.id, [{"id": channel.id, "position": position} for position, channel in enumerate(ordered)])


def report(added):
    """The reply to the user about what was Added."""
    lines = []
    if added.created:
        lines.append(f"Created {', '.join(f'<#{channel.id}>' for channel in added.created)} :muscle:")
    if added.existing:
        lines.append(f"Already exists: {', '.join(f'<#{category.channel_id}>' for category in added.existing)}")
    if added.invalid:
        names = ", ".join(f"`{name}`" for name in added.invalid)
        lines.append(f"Skipped {names}: a category name needs letters or digits")
    return "\n".join(lines) or "Give the category names, comma-separated: `/add-category web, crypto, pwn`"
