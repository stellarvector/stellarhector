"""Archiving a CTF, by /archive-ctf and when it is locked."""

import asyncio
from datetime import datetime
from typing import cast
from zoneinfo import ZoneInfo

import discord

from archive.ctf_archive import CtfArchive
from archive.repository import Repository
from ctf import store
from ctf.location import without_bot_channel
from ctf.models import Ctf


async def archive_ctf(guild: discord.Guild, ctf: Ctf, now: datetime, repository: Repository, zone: ZoneInfo) -> None:
    """Archive the main channel and every text channel in the CTF's category except #bot, commit and push it, and
    record that it was archived. On failure the written files are removed again and nothing is recorded, so it can
    be retried."""
    category = cast(discord.CategoryChannel | None, guild.get_channel(ctf.category_id))
    main_channel = cast(discord.TextChannel | None, guild.get_channel(ctf.main_channel_id))
    # Only text channels have both messages and threads; voice and forum channels are left out
    category_channels = (
        []
        if category is None
        else [
            cast(discord.TextChannel, channel)
            for channel in without_bot_channel(ctf, category.channels)
            if channel.id != ctf.main_channel_id
            and hasattr(channel, "history")
            and hasattr(channel, "archived_threads")
        ]
    )

    async with repository.lock:
        await repository.sync()
        year = now.astimezone(zone).year
        snapshot = await CtfArchive.load(ctf.name, main_channel, category_channels, repository.path, year, zone)
        try:
            # Writing the files downloads the attachments
            await asyncio.to_thread(snapshot.generate_files)
            await repository.save(f"Archive {snapshot.name} {year}", [str(year), "index.html"])
        except Exception:
            # Not on cancellation: the thread writing the files can't be stopped
            await asyncio.to_thread(snapshot.discard_files)
            raise
    store.mark_archived(ctf.id, now)
