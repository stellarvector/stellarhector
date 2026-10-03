"""Archiving a CTF to the archive repository, by /archive-ctf and when it is locked (utils/ctf_lock.py)."""
import asyncio

from utils import ctf_places, ctfs
from utils.archive.ctf import CtfArchive


async def archive(guild, ctf, now):
    """Archive the CTF's main channel and every other text channel in its category but #bot (its categories, with a page
    per thread), commit and push it as the settings say, and record now as its archive time. Writing the files
    (attachments are downloaded) and the git work run off the event loop. A failure is raised, and then no archive
    time is recorded and the files written are taken away again, so it can be tried again.

    A category deleted by hand leaves only the main channel to archive (when that still exists)."""
    category = guild.get_channel(ctf.category_id)
    main_channel = guild.get_channel(ctf.main_channel_id)
    # Only text channels have both messages and threads; a voice or forum channel, say, is left out
    category_channels = [] if category is None else [
        channel for channel in ctf_places.without_bot_channel(ctf, category.channels)
        if channel.id != ctf.main_channel_id and hasattr(channel, "history") and hasattr(channel, "archived_threads")]

    snapshot = await CtfArchive.init(ctf.name, main_channel, category_channels)
    try:
        await asyncio.to_thread(snapshot.generate_files)
        await snapshot.save()
    except Exception:
        # Not on cancellation: the thread writing the files can't be stopped, and goes on
        await asyncio.to_thread(snapshot.discard_files)
        raise
    ctfs.mark_archived(ctf.id, now)
