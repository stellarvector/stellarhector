# Runs the automatic timeline of the CTFs on CTFtime: sets up the CTFs linked from a calendar session 3 days before
# they start, and makes their last call, release, lock and archive, and removal reminder at their times
# Runs by itself every tick; the steps are the same functions the commands use
# Posts what it did, and a step that keeps failing (once), in the CTF's #bot, or in ADMIN_CHANNEL_ID before setup
import asyncio
from datetime import datetime, timedelta, timezone

import core.bot as bot
import core.config as config_helpers
import core.scheduler as scheduler
from command_handlers.lock_ctf import lock_roles
from command_handlers.setup_ctf import settings as setup_settings
from utils import ctf_archive, ctf_join, ctf_lock, ctf_release, ctf_setup, ctf_timeline

# A lock archives the CTF, git push included, which can take a while; stopping it halfway would leave it unarchived
TIMEOUT = timedelta(minutes=30)


class Actions:
    """The lifecycle steps on the server, as ctf_timeline.run does them."""

    def __init__(self, guild):
        self.guild = guild

    async def setup(self, ctftime_id, title):
        return await ctf_setup.setup_ctf(self.guild, title, ctftime_id, setup_settings())

    async def last_call(self, ctf, now):
        ctf = await ctf_join.last_call(self.guild, ctf, bot.channel_id("UPCOMING_CTFS_CHANNEL_ID"), now)
        return f":robot: Automatic last call: the join message is posted again in <#{ctf.join_channel_id}>."

    async def release(self, ctf, now):
        await ctf_release.release(self.guild, ctf, config_helpers.role_name(bot.config, "MEMBER_ROLE"), now)
        return ":robot: Released automatically: every member can read and write in the CTF now, and joining is closed."

    async def lock(self, ctf, now):
        locked = await ctf_lock.lock(self.guild, ctf, lock_roles(), now, ctf_archive.archive)
        return f":robot: Automatic lock: {locked.notice}"


async def run_timeline():
    """The ctf-timeline job: run the automatic steps that are due now."""
    guild = bot.client.get_guild(bot.guild.id) or await bot.client.fetch_guild(bot.guild.id)
    await ctf_timeline.run(datetime.now(timezone.utc), Actions(guild), _notify)


async def _notify(ctf, message):
    await asyncio.wait_for(bot.alert_ctf(ctf, message), timeout=scheduler.ALERT_TIMEOUT.total_seconds())


scheduler.register(scheduler.Job("ctf-timeline", scheduler.every_minutes(5), run_timeline, timeout=TIMEOUT))
