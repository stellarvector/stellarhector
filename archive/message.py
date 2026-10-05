import shutil
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import discord
import emoji
import markdown
import nh3

from archive.naming import file_name

IMAGE_EXTENSIONS = (".png", ".gif", ".jpg", ".jpeg")
DOWNLOAD_TIMEOUT_SECONDS = 60

# Discord's CDN refuses urllib's default User-Agent
_opener = urllib.request.build_opener()
_opener.addheaders = [("User-agent", "Mozilla/5.0")]


class MessageArchive:
    """A message as archive/templates/message.html shows it, with its times in `zone`."""

    def __init__(self, message: discord.Message, zone: ZoneInfo) -> None:
        self.original = message
        self.zone = zone

    @property
    def id(self) -> int:
        return self.original.id

    def timestamp(self) -> str:
        return self._local_time(self.original.created_at)

    def edit_timestamp(self) -> str | None:
        edited_at = self.original.edited_at
        return None if edited_at is None else self._local_time(edited_at)

    def safe_body(self) -> str:
        """Return the message's content and attachments as sanitized HTML."""
        content = self._format_content()
        if content.startswith("https://tenor.com/"):
            content = f"![{content}]({content.strip()}.gif)"

        md = emoji.emojize(content + "\n" + self._format_attachments(), language="alias")
        html = markdown.markdown(md, extensions=["sane_lists", "nl2br", "fenced_code", "pymdownx.magiclink"])
        return nh3.clean(html)

    def download_attachments(self, folder: Path) -> None:
        for attachment in self.original.attachments:
            _download(attachment.url, folder / attachment_file(attachment))

    def _local_time(self, moment: datetime) -> str:
        return moment.astimezone(self.zone).strftime("%Y-%m-%d %H:%M:%S")

    def _format_content(self) -> str:
        content = self.original.clean_content or ""
        if self.original.system_content and self.original.content != self.original.system_content:
            content = f"_{self.original.system_content}_"

        if content:
            # Two trailing spaces make Markdown keep the line break
            content = (content + "  ").replace("\n", "  \n")
        return content

    def _format_attachments(self) -> str:
        attachments = ""
        for attachment in self.original.attachments:
            if attachment.filename.lower().endswith(IMAGE_EXTENSIONS):
                attachments += "!"
            attachments += f"[{attachment.filename}](./attachments/{attachment_file(attachment)}) "

        if attachments:
            attachments += "  "
        return attachments


# What an archive page template renders: messages, and dicts for inline threads and links to challenge pages
PageItem = MessageArchive | dict[str, object]


def attachment_file(attachment: discord.Attachment) -> str:
    """Return the name an attachment is saved under. The ID prefix keeps names from clashing."""
    return f"{attachment.id}_{file_name(attachment.filename)}"


def _download(url: str, path: Path) -> None:
    with _opener.open(url, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response, open(path, "wb") as file:
        shutil.copyfileobj(response, file)
