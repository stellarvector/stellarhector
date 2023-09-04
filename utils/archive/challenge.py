from utils.archive.message import MessageArchive
from utils.archive.thread import ThreadArchive
import discord

class ChallengeArchive():
    @classmethod
    async def init(cls, challenge: discord.TextChannel):
        self = ChallengeArchive()

        self.name = challenge.name
        self.link = f"./{self.name}.html"

        self.__challenge: discord.TextChannel = challenge
        self.__messages: list[MessageArchive] = [
            await MessageArchive.init(message)
                async for message in self.__challenge.history(limit=None, oldest_first=True)
        ]
        self.__threads: dict[int,ThreadArchive] = {
            thread.id: await ThreadArchive.init(thread)
                for thread in self.__challenge.threads
        }
        self.__threads.update({
            thread.id: await ThreadArchive.init(thread)
                async for thread in self.__challenge.archived_threads(limit=None)
        })

        return self

    def fetch_data(self, attachment_path):
        challenge_messages = []

        for message in self.__messages:
            challenge_messages.append(message)
            message.download_attachments(attachment_path)

            if message.id in self.__threads:
                challenge_messages.append(self.__threads[message.id].fetch_data(attachment_path))

        return challenge_messages
