"""Archiving a regular (non-CTF) channel with /archive-channel: a single page with its threads inline, in
channels/<category>/<channel>/ of the archive repository."""

import asyncio
import shutil
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Self
from zoneinfo import ZoneInfo

import discord

from archive.naming import first_free, normalize_name
from archive.page import ChannelPage
from archive.render import fill_marker, render
from archive.repository import Repository

CHANNELS_FOLDER = "channels"
UNCATEGORIZED_FOLDER = "uncategorized"


# Asked when the channel was archived before, with its category folder and archive folder. Returns True to overwrite
# that archive, False to keep both, and None to cancel.
ChooseOverwrite = Callable[[str, str], Awaitable[bool | None]]


async def archive_channel(
    channel: discord.TextChannel, repository: Repository, zone: ZoneInfo, choose_overwrite: ChooseOverwrite
) -> "ChannelArchive | None":
    """Archive the channel, then commit and push it. Return None when `choose_overwrite` cancels."""
    async with repository.lock:
        # Sync first, so the check sees the latest archives
        await repository.sync()
        overwrite = False
        category, name = category_folder(channel), channel_folder(channel)
        if is_archived(repository.path, category, name):
            choice = await choose_overwrite(category, name)
            if choice is None:
                return None
            overwrite = choice

        archive = await ChannelArchive.load(channel, repository.path, zone)
        # Writing the files downloads the attachments
        await asyncio.to_thread(archive.generate_files, overwrite)
        await repository.save(archive.commit_message, [CHANNELS_FOLDER, "index.html"])
        return archive


def category_folder(channel: discord.TextChannel) -> str:
    if channel.category is None:
        return UNCATEGORIZED_FOLDER
    return normalize_name(channel.category.name, fallback=UNCATEGORIZED_FOLDER)


def channel_folder(channel: discord.TextChannel) -> str:
    """Return the channel's archive folder, without the number a second copy gets."""
    return normalize_name(channel.name, fallback=f"channel-{channel.id}")


def is_archived(root: Path, category: str, name: str) -> bool:
    return (root / CHANNELS_FOLDER / category / name).exists()


class ChannelArchive:
    """The archive of a channel, in channels/<category>/<archive_name>/ under `root`."""

    def __init__(self, root: Path, category: str, archive_name: str, page: ChannelPage) -> None:
        self.root = root
        self.category = category
        self.archive_name = archive_name
        self.page = page

    @classmethod
    async def load(cls, channel: discord.TextChannel, root: Path, zone: ZoneInfo) -> Self:
        return cls(
            Path(root),
            category_folder(channel),
            channel_folder(channel),
            await ChannelPage.load(channel, path=None, zone=zone),
        )

    @property
    def commit_message(self) -> str:
        return f"Archive channel {self.category}/{self.archive_name}"

    def generate_files(self, overwrite: bool = False) -> None:
        """Write the channel's page and attachments. With `overwrite`, an existing archive of the same name is
        replaced; otherwise the new one goes next to it with a number (-2, -3, ...). This blocks while attachments
        download, so run it off the event loop."""
        self._add_channels_folder_if_necessary()

        if overwrite and is_archived(self.root, self.category, self.archive_name):
            # Git keeps the history of the replaced archive
            shutil.rmtree(self._folder)
        else:
            self.archive_name = self._free_archive_name()
            self._add_to_channels_index()

        attachments = self._folder / "attachments"
        attachments.mkdir(parents=True)
        html = render(
            "channel.html",
            channel_name=self.page.name,
            category=self.category,
            archive_name=self.archive_name,
            messages=self.page.download_and_list_items(attachments),
        )
        (self._folder / f"{self.archive_name}.html").write_text(html)

    @property
    def _folder(self) -> Path:
        return self.root / CHANNELS_FOLDER / self.category / self.archive_name

    def _free_archive_name(self) -> str:
        return first_free(self.archive_name, lambda name: is_archived(self.root, self.category, name))

    def _add_channels_folder_if_necessary(self) -> None:
        channels = self.root / CHANNELS_FOLDER
        if channels.exists():
            return

        channels.mkdir(parents=True)
        fill_marker(self.root / "index.html", "<!--add-year-->", render("channelslink.html"))
        (channels / "index.html").write_text(render("channels.html"))

    def _add_to_channels_index(self) -> None:
        link = render(
            "channellink.html",
            channel={
                "link": f"./{self.category}/{self.archive_name}/{self.archive_name}.html",
                "name": f"{self.category} / {self.archive_name}",
            },
        )
        fill_marker(self.root / CHANNELS_FOLDER / "index.html", "<!--add-channel-->", link)
