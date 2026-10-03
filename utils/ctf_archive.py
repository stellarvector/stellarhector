"""Archiving a CTF to the archive repository, by /archive-ctf and when it is locked (utils/ctf_lock.py)."""
from utils import ctf_places, ctfs
from utils.archive.ctf import CtfArchive


async def archive(guild, ctf, now):
    """Archive the CTF's main channel and every other text channel in its category but #bot (its categories, with a page
    per thread), commit and push it as the settings say, and record now as its archive time. The git work runs off the
    event loop. A failure is raised, and then no archive time is recorded."""
    category = guild.get_channel(ctf.category_id)
    main_channel = guild.get_channel(ctf.main_channel_id)
    # Only text channels have both messages and threads; a voice or forum channel, say, is left out
    category_channels = [channel for channel in ctf_places.without_bot_channel(ctf, category.channels)
                         if channel.id != ctf.main_channel_id and hasattr(channel, "history")
                         and hasattr(channel, "archived_threads")]

    snapshot = await CtfArchive.init(ctf.name, main_channel, category_channels)
    snapshot.generate_files()
    await snapshot.save()
    ctfs.mark_archived(ctf.id, now)
