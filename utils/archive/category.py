from utils.archive.message import MessageArchive
from utils.archive.naming import relative_link, unique_name
import discord

# The category's own page in its folder; no challenge page may take its name
CATEGORY_PAGE = "index"

class CategoryArchive():
    """A category channel of a CTF: its own page with the messages posted directly in it, and a page per thread in it
    (its challenges), all in one folder."""
    @classmethod
    async def init(cls, channel: discord.TextChannel, folder):
        self = CategoryArchive()

        self.name = channel.name
        self.folder = folder
        self.path = f"{folder}/{CATEGORY_PAGE}.html"

        self.__messages: list[MessageArchive] = [
            await MessageArchive.init(message)
                async for message in channel.history(limit=None, oldest_first=True)
        ]

        taken = {CATEGORY_PAGE}
        self.challenges: list[ChallengeThreadArchive] = [
            await ChallengeThreadArchive.init(
                thread, f"{folder}/{unique_name(thread.name, taken, fallback=f'thread-{thread.id}')}.html")
                for thread in await CategoryArchive.threads(channel)
        ]

        return self

    @staticmethod
    async def threads(channel):
        """All threads of the channel, active and archived (public and private), oldest first."""
        threads = {thread.id: thread for thread in channel.threads}
        for private in (False, True):
            threads.update({thread.id: thread async for thread in channel.archived_threads(private=private, limit=None)})

        return sorted(threads.values(), key=lambda thread: thread.id)

    def fetch_data(self, attachment_path):
        """The category page's messages, with a link to a challenge's page at the message its thread was made on, or
        at Discord's notice that it was made when it was made on none. Challenges with neither (deleted) are linked at
        the end."""
        challenges = {challenge.id: challenge for challenge in self.challenges}
        category_messages = []

        for message in self.__messages:
            category_messages.append(message)
            message.download_attachments(attachment_path)

            thread_id = CategoryArchive.thread_made_at(message.direct)
            if thread_id in challenges:
                category_messages.append(self.challenge_link(challenges.pop(thread_id)))

        category_messages += [self.challenge_link(challenge) for challenge in challenges.values()]
        return category_messages

    @staticmethod
    def thread_made_at(message: discord.Message):
        """The ID of the thread made at the message: on it (the thread has its ID), or announced by it."""
        if message.type == discord.MessageType.thread_created and message.reference is not None:
            return message.reference.channel_id
        return message.id

    def challenge_link(self, challenge):
        return {"is_challenge_link": True, "name": challenge.name, "link": relative_link(self.path, challenge.path)}


class ChallengeThreadArchive():
    """A challenge thread of a category channel, with a page of its own."""
    @classmethod
    async def init(cls, thread: discord.Thread, path):
        self = ChallengeThreadArchive()

        self.id = thread.id
        self.name = thread.name
        self.path = path

        # A thread made on a message starts with a reference to it, which is on the category's page
        self.__messages: list[MessageArchive] = [
            await MessageArchive.init(message)
                async for message in thread.history(limit=None, oldest_first=True)
                if message.type != discord.MessageType.thread_starter_message
        ]

        return self

    def fetch_data(self, attachment_path):
        for message in self.__messages:
            message.download_attachments(attachment_path)

        return self.__messages
