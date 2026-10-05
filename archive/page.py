from pathlib import Path
from typing import Self
from zoneinfo import ZoneInfo

import discord

from archive.message import MessageArchive, PageItem
from archive.thread import ThreadArchive


class ChannelPage:
    """A channel on a single page, with each thread inline after the message it was made on."""

    def __init__(
        self, name: str, path: str | None, messages: list[MessageArchive], threads: dict[int, ThreadArchive]
    ) -> None:
        self.name = name
        self.path = path
        self.messages = messages
        # Keyed by the ID of the message each thread was made on, which is also the thread's ID
        self.threads = threads

    @classmethod
    async def load(cls, channel: discord.TextChannel, path: str | None, zone: ZoneInfo) -> Self:
        messages = [MessageArchive(message, zone) async for message in channel.history(limit=None, oldest_first=True)]
        threads = {thread.id: await ThreadArchive.load(thread, zone) for thread in channel.threads}
        threads.update(
            {thread.id: await ThreadArchive.load(thread, zone) async for thread in channel.archived_threads(limit=None)}
        )
        return cls(channel.name, path, messages, threads)

    def download_and_list_items(self, attachment_folder: Path) -> list[PageItem]:
        items: list[PageItem] = []
        for message in self.messages:
            items.append(message)
            message.download_attachments(attachment_folder)
            if message.id in self.threads:
                items.append(self.threads[message.id].download_and_list_items(attachment_folder))
        return items
