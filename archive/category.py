from pathlib import Path
from typing import Self
from zoneinfo import ZoneInfo

import discord

from archive.message import MessageArchive, PageItem
from archive.naming import relative_link, unique_name
from utils import discord_objects

# The name of a category's own page in its folder, which no challenge page may take
CATEGORY_PAGE = "index"


class ChallengeThreadArchive:
    """A thread in a category channel, archived on a page of its own."""

    def __init__(self, id: int, name: str, path: str, messages: list[MessageArchive]) -> None:
        self.id = id
        self.name = name
        self.path = path
        self.messages = messages

    @classmethod
    async def load(cls, thread: discord.Thread, path: str, zone: ZoneInfo) -> Self:
        # A thread made on a message starts with a reference to it, and that message is already on the category's page
        messages = [
            MessageArchive(message, zone)
            async for message in thread.history(limit=None, oldest_first=True)
            if message.type != discord.MessageType.thread_starter_message
        ]
        return cls(thread.id, thread.name, path, messages)

    def download_and_list_items(self, attachment_folder: Path) -> list[MessageArchive]:
        for message in self.messages:
            message.download_attachments(attachment_folder)
        return self.messages


class CategoryArchive:
    """A category channel of a CTF, archived in its own folder: a page for the messages posted directly in it, and a
    page for each of its threads (its challenges)."""

    def __init__(
        self, name: str, folder: str, messages: list[MessageArchive], challenges: list[ChallengeThreadArchive]
    ) -> None:
        self.name = name
        self.folder = folder
        self.path = f"{folder}/{CATEGORY_PAGE}.html"
        self.messages = messages
        self.challenges = challenges

    @classmethod
    async def load(cls, channel: discord.TextChannel, folder: str, zone: ZoneInfo) -> Self:
        messages = [MessageArchive(message, zone) async for message in channel.history(limit=None, oldest_first=True)]
        taken = {CATEGORY_PAGE}
        challenges = [
            await ChallengeThreadArchive.load(
                thread, f"{folder}/{unique_name(thread.name, taken, fallback=f'thread-{thread.id}')}.html", zone
            )
            for thread in await discord_objects.all_threads(channel)
        ]
        return cls(channel.name, folder, messages, challenges)

    def download_and_list_items(self, attachment_folder: Path) -> list[PageItem]:
        """Each challenge is linked right after the message its thread was made on, or after Discord's notice that the
        thread was created. Challenges with neither (because it was deleted) are linked at the end."""
        challenges = {challenge.id: challenge for challenge in self.challenges}
        items: list[PageItem] = []
        for message in self.messages:
            items.append(message)
            message.download_attachments(attachment_folder)

            thread_id = thread_made_at(message.original)
            if thread_id in challenges:
                items.append(self._challenge_link(challenges.pop(thread_id)))

        items += [self._challenge_link(challenge) for challenge in challenges.values()]
        return items

    def _challenge_link(self, challenge: ChallengeThreadArchive) -> dict[str, object]:
        return {"is_challenge_link": True, "name": challenge.name, "link": relative_link(self.path, challenge.path)}


def thread_made_at(message: discord.Message) -> int:
    """Return the ID of the thread that belongs to `message`. A thread made on a message shares its ID; a "thread
    created" notice refers to its thread."""
    if message.type == discord.MessageType.thread_created and message.reference is not None:
        return message.reference.channel_id
    return message.id
