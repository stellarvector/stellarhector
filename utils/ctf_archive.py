"""Archiving a CTF to the archive repository, by /archive-ctf and when it is locked (utils/ctf_lock.py)."""
from utils import ctf_places, ctfs
from utils.archive.ctf import CtfArchive


async def archive(guild, ctf, now):
    """Archive every channel in the CTF's category but #bot, commit and push it as the settings say, and record now as
    its archive time. The git work runs off the event loop. A failure is raised, and then no archive time is
    recorded."""
    category = guild.get_channel(ctf.category_id)
    channels = ctf_places.without_bot_channel(ctf, category.channels)

    snapshot = await CtfArchive.init(ctf.name, channels)
    snapshot.generate_files()
    await snapshot.save()
    ctfs.mark_archived(ctf.id, now)
