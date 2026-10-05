from pathlib import Path
from typing import Self
from zoneinfo import ZoneInfo

import discord

from archive.message import MessageArchive


class ThreadArchive:
    """A thread shown inline on its channel's page, after the message it was made on."""

    def __init__(self, name: str, messages: list[MessageArchive]) -> None:
        self.name = name
        self.messages = messages

    @classmethod
    async def load(cls, thread: discord.Thread, zone: ZoneInfo) -> Self:
        messages = [MessageArchive(message, zone) async for message in thread.history(limit=None, oldest_first=True)]
        # A thread starts with a reference to the message it was made on, which is already on the channel's page
        return cls(thread.name, messages[1:])

    def download_and_list_items(self, attachment_folder: Path) -> dict[str, object]:
        for message in self.messages:
            message.download_attachments(attachment_folder)
        return {"is_thread": True, "name": self.name, "messages": self.messages}
