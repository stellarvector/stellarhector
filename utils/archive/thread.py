from utils.archive.message import MessageArchive
import discord

class ThreadArchive():
    @classmethod
    async def init(cls, thread: discord.Thread):
        self = ThreadArchive()

        self.__thread: discord.Thread = thread
        self.__messages: list[MessageArchive] = [
            await MessageArchive.init(message)
                async for message in thread.history(oldest_first=True)
        ]

        return self

    def fetch_data(self, attachment_path):
        for message in self.__messages[1:]:
            message.download_attachments(attachment_path)

        return {
            "is_thread": True,
            "name": self.__thread.name,
            "messages": self.__messages[1:]
        }
