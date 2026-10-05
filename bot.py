import asyncio
import logging
from collections.abc import Callable, Iterable
from typing import cast

import discord
from discord.ext import commands

from archive.repository import Repository
from core import errors
from core.scheduler import ALERT_TIMEOUT, Scheduler
from core.settings import Settings
from ctf.models import Ctf

log = logging.getLogger("bot")


class Hector(commands.Bot):
    """The bot of one server. Its features are the cogs in cogs/, whose commands are added to that server only."""

    def __init__(self, settings: Settings, cogs: Iterable[Callable[["Hector"], commands.Cog]] = ()) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        # Reading message content is for the archive: the bot has slash commands only, no text commands
        super().__init__(command_prefix=commands.when_mentioned, help_command=None, intents=intents)

        self.settings = settings
        self.home = discord.Object(id=settings.guild_id)
        self.scheduler = Scheduler(settings.watchdog_limit, alert=self.alert_admins)
        self.archive_repository = Repository(settings.archive)
        self._cog_types = list(cogs)
        self.tree.error(errors.on_app_command_error)

    async def setup_hook(self) -> None:
        await self.add_cogs()
        synced = await self.tree.sync(guild=self.home)
        log.debug(f"{len(synced)} commands registered and synced")

    async def add_cogs(self) -> None:
        for cog_type in self._cog_types:
            await self.add_cog(cog_type(self), guild=self.home)
        log.debug(f"{len(self._cog_types)} cogs loaded")

    async def on_message(self, message: discord.Message) -> None:
        # The bot has no text commands, so messages aren't parsed for them
        return

    async def on_ready(self) -> None:
        # on_ready fires again after a reconnect, and the scheduler only starts once
        self.scheduler.start()
        log.info(f"Logged on as {self.user}!")

    async def home_guild(self) -> discord.Guild:
        return self.get_guild(self.home.id) or await self.fetch_guild(self.home.id)

    async def channel(self, channel_id: int) -> discord.abc.Messageable:
        found = self.get_channel(channel_id) or await self.fetch_channel(channel_id)
        return cast(discord.abc.Messageable, found)

    async def alert_admins(self, message: str) -> None:
        """Post `message` in the admin channel, or only log it when that channel isn't configured. Gives up after
        ALERT_TIMEOUT."""
        await asyncio.wait_for(self._post_for_admins(message), timeout=ALERT_TIMEOUT.total_seconds())

    async def try_alert_admins(self, message: str) -> bool:
        try:
            await self.alert_admins(message)
        except Exception:
            log.exception(f"Could not post the alert: {message}")
            return False
        return True

    async def alert_ctf(self, ctf: Ctf | None, message: str) -> None:
        """Post `message` in the #bot channel of `ctf`. When `ctf` is None or its #bot channel no longer exists, the
        admins are alerted instead. Gives up after ALERT_TIMEOUT."""
        await asyncio.wait_for(self._post_for_ctf(ctf, message), timeout=ALERT_TIMEOUT.total_seconds())

    async def _post_for_ctf(self, ctf: Ctf | None, message: str) -> None:
        if ctf is not None:
            try:
                bot_channel = await self.channel(ctf.bot_channel_id)
            except discord.NotFound:
                log.warning(f"The #bot channel of CTF {ctf.name!r} no longer exists, alerting the admins")
            else:
                await bot_channel.send(message, allowed_mentions=discord.AllowedMentions.none())
                return
        await self._post_for_admins(message)

    async def _post_for_admins(self, message: str) -> None:
        admin_channel_id = self.settings.channels.admin
        if admin_channel_id is None:
            log.warning(f"ADMIN_CHANNEL_ID is not configured, alert not posted: {message}")
            return
        admin_channel = await self.channel(admin_channel_id)
        await admin_channel.send(message, allowed_mentions=discord.AllowedMentions.none())
