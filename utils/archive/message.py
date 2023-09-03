import discord
import core.bot as bot
import datetime
import markdown
import emoji
import nh3
from urllib.request import urlretrieve, build_opener, install_opener


class MessageArchive():
    @classmethod
    async def init(cls, message: discord.Message):
        self = MessageArchive()

        self.id = message.id
        self.__message = message
        self.direct = message

        return self

    def timestamp(self):
        return self.__message.created_at.strftime('%Y-%m-%d %H:%M:%S')

    def edit_timestamp(self):
        time = False

        if self.__message.edited_at is not None:
            time = self.__message.edited_at.strftime('%Y-%m-%d %H:%M:%S')

        return time

    def safe_body(self):
        content = self._format_content()

        if content.startswith("https://tenor.com/"):
            content = f"![{content}]({content.strip()}.gif)"

        md = content + "\n" + self._format_attachments()
        emoji_md = emoji.emojize(md, language="alias")

        html = markdown.markdown(emoji_md, extensions=["sane_lists", "nl2br", "fenced_code", "pymdownx.magiclink"])
        safe_html = nh3.clean(html)

        return safe_html

    def _format_content(self):
        content = ""

        if self.__message.clean_content:
            content = self.__message.clean_content

        if self.__message.system_content and self.__message.content != self.__message.system_content:
            content = f"_{self.__message.system_content}_"

        if content:
            content += "  "
            content = content.replace("\n", "  \n")

        return content

    def _format_attachments(self):
        attachments = ""

        for attachment in self.__message.attachments:
            if attachment.filename.endswith((".png",".gif",".jpg",".jpeg")):
                attachments += "!"
            attachments += f"[{attachment.filename}]"
            attachments += f"(./attachments/{attachment.id}_{attachment.filename}) "

        if attachments:
            attachments += "  "
        return attachments

    def download_attachments(self, attachment_path):
        year = datetime.datetime.now().year
        opener = build_opener()
        opener.addheaders = [("User-agent", "Mozilla/5.0")]
        install_opener(opener)

        for attachment in self.__message.attachments:
            urlretrieve(
                attachment.url,
                f"{bot.config.get('ARCHIVE_PATH')}{attachment_path}/{attachment.id}_{attachment.filename}"
            )
