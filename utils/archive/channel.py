from utils.archive.challenge import ChallengeArchive
from utils.archive.ctf import CtfArchive
from utils.archive.naming import normalize_name
import core.bot as bot
import discord
import os
import shutil

CHANNELS_FOLDER = "channels"
UNCATEGORIZED_FOLDER = "uncategorized"

class ChannelArchive():
    @classmethod
    async def init(cls, channel: discord.TextChannel):
        self = ChannelArchive()

        # First sync archive repository
        _ = CtfArchive.get_archive_repository()

        self.name = channel.name
        self.category = ChannelArchive.category_folder(channel)
        self.archive_name = ChannelArchive.channel_folder(channel)
        self.__channel = await ChallengeArchive.init(channel)

        return self

    @staticmethod
    def category_folder(channel: discord.TextChannel):
        if channel.category is None:
            return UNCATEGORIZED_FOLDER

        return normalize_name(channel.category.name, fallback=UNCATEGORIZED_FOLDER)

    @staticmethod
    def channel_folder(channel: discord.TextChannel):
        return normalize_name(channel.name, fallback=f"channel-{channel.id}")

    @staticmethod
    def is_archived(category, name):
        archive_path = bot.config.get("ARCHIVE_LOCAL_PATH")
        return os.path.exists(os.path.join(archive_path, CHANNELS_FOLDER, category, name))

    def generate_files(self, overwrite=False):
        archive_path = bot.config.get("ARCHIVE_LOCAL_PATH")

        self.add_channels_folder_if_necessary(archive_path)

        if overwrite and ChannelArchive.is_archived(self.category, self.archive_name):
            # Replace the previous archive, git keeps the history
            shutil.rmtree(os.path.join(archive_path, CHANNELS_FOLDER, self.category, self.archive_name))
        else:
            self.archive_name = self.create_archive_name()
            self.add_channel_to_channels_index(archive_path)

        channel_path = os.path.join(archive_path, CHANNELS_FOLDER, self.category, self.archive_name)
        os.makedirs(os.path.join(channel_path, "attachments"))

        channel_data = self.__channel.fetch_data(f"/{CHANNELS_FOLDER}/{self.category}/{self.archive_name}/attachments")

        channel_template = bot.jinja_env.get_template("channel.html")
        channel_html = channel_template.render(
            channel_name=self.name,
            category=self.category,
            archive_name=self.archive_name,
            messages=channel_data)

        with open(os.path.join(channel_path, f"{self.archive_name}.html"), "w+") as f:
            f.write(channel_html)

    def create_archive_name(self):
        if not ChannelArchive.is_archived(self.category, self.archive_name):
            return self.archive_name

        for i in range(2, 100):
            if not ChannelArchive.is_archived(self.category, f"{self.archive_name}-{i}"):
                return f"{self.archive_name}-{i}"

        raise RuntimeError("No free archive name could be found")

    def add_channels_folder_if_necessary(self, archive_path):
        channels_folder_path = os.path.join(archive_path, CHANNELS_FOLDER)
        if os.path.exists(channels_folder_path):
            return

        os.makedirs(channels_folder_path)

        channels_link_template = bot.jinja_env.get_template("channelslink.html")
        channels_link_html = channels_link_template.render()

        index_path = os.path.join(archive_path, "index.html")
        with open(index_path, "r+") as index_file:
            index_html = index_file.read()
            index_file.seek(0)
            index_html = index_html.replace("<!--add-year-->", channels_link_html)
            index_file.write(index_html)

        channels_template = bot.jinja_env.get_template("channels.html")
        channels_html = channels_template.render()

        channels_index_path = os.path.join(channels_folder_path, "index.html")
        with open(channels_index_path, "w+") as channels_file:
            channels_file.write(channels_html)

    def add_channel_to_channels_index(self, archive_path):
        channel_link_template = bot.jinja_env.get_template("channellink.html")
        channel_link_html = channel_link_template.render(channel={"link": f"./{self.category}/{self.archive_name}/{self.archive_name}.html", "name": f"{self.category} / {self.archive_name}"})

        channels_index_path = os.path.join(archive_path, CHANNELS_FOLDER, "index.html")
        with open(channels_index_path, "r+") as channels_file:
            channels_html = channels_file.read()
            channels_file.seek(0)
            channels_html = channels_html.replace("<!--add-channel-->", channel_link_html)
            channels_file.write(channels_html)

    def save(self):
        repository = CtfArchive.get_archive_repository()
        if int(bot.config.get("SHOULD_COMMIT")):
            # --all also stages files removed by overwriting an archived channel
            repository.git.add("--all", CHANNELS_FOLDER, "index.html")
            repository.index.commit(f"Archive channel {self.category}/{self.archive_name}")

            if int(bot.config.get("SHOULD_PUSH")):
                origin = repository.remote(name="origin")
                origin.push()
