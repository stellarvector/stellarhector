"""Stand-ins for Discord (and CTFtime) objects, with just what the code under test uses of them."""

import asyncio
import itertools
from types import SimpleNamespace

import discord

from feeds.ctftime import CtftimeError
from tests.factories import SETTINGS, utc

_ids = itertools.count(1000)


def http_error(error, status):
    return error(SimpleNamespace(status=status, reason=error.__name__), "fake")


class FakeRole:
    def __init__(self, name, position=0):
        self.id, self.name, self.position = next(_ids), name, position


class FakeMember:
    def __init__(self, guild, *role_names, joined_at=utc(2025, 9, 1, 12), dms_closed=False):
        self.guild, self.id, self.joined_at, self.dms_closed = guild, next(_ids), joined_at, dms_closed
        self.roles_fail = False
        self.roles = [guild.default_role] + [guild.role(name) for name in role_names]
        self.dms = []
        guild.members.append(self)

    @property
    def mention(self):
        return f"<@{self.id}>"

    async def add_roles(self, *roles):
        # Let other clicks run in between, as a real request to Discord would
        await asyncio.sleep(0)
        if self.roles_fail:
            raise http_error(discord.HTTPException, 500)
        self.roles += [role for role in roles if role not in self.roles]

    async def remove_roles(self, *roles):
        self.roles = [role for role in self.roles if role not in roles]

    async def send(self, content):
        if self.dms_closed:
            raise http_error(discord.Forbidden, 403)
        self.dms.append(content)


_KEEP = object()


class FakeMessage:
    def __init__(self, content, view=None):
        self.id, self.content, self.view = next(_ids), content, view

    async def edit(self, content=_KEEP, view=_KEEP, allowed_mentions=None):
        if content is not _KEEP:
            self.content = content
        if view is not _KEEP:
            self.view = view


class FakeChannel:
    def __init__(self, name):
        self.id, self.name, self.messages = next(_ids), name, []

    async def send(self, content, view=None, allowed_mentions=None):
        self.messages.append(FakeMessage(content, view))
        return self.messages[-1]

    def get_partial_message(self, message_id):
        return FakePartialMessage(self, message_id)

    async def fetch_message(self, message_id):
        return self.get_partial_message(message_id)._message()


class FakePartialMessage:
    """A message of channel known only by its ID, as Discord gives it: editing or deleting a message that is gone
    fails."""

    def __init__(self, channel, message_id):
        self.channel, self.id = channel, message_id

    def _message(self):
        message = next((message for message in self.channel.messages if message.id == self.id), None)
        if message is None:
            raise http_error(discord.NotFound, 404)
        return message

    async def edit(self, content=_KEEP, view=_KEEP, allowed_mentions=None):
        await self._message().edit(content, view, allowed_mentions)

    async def delete(self):
        self.channel.messages.remove(self._message())


class FakeGuild:
    def __init__(self):
        self.default_role = FakeRole("@everyone")
        self.roles = [self.default_role] + [
            FakeRole(name, position)
            for position, name in enumerate(
                [
                    "sv{follower}",
                    "sv{player}",
                    "sv{known-player}",
                    "sv{core-player}",
                    "sv{moderator}",
                    "sv{manager}",
                    "sv{admin}",
                    "Foo CTF",
                ],
                1,
            )
        ]
        self.channels = [FakeChannel("upcoming-ctfs"), FakeChannel("foo-ctf"), FakeChannel("bot")]
        self.members = []

    def role(self, name):
        return next(role for role in self.roles if role.name == name)

    def channel(self, name):
        return next(channel for channel in self.channels if channel.name == name)

    def get_role(self, role_id):
        return next((role for role in self.roles if role.id == role_id), None)

    def get_channel(self, channel_id):
        return next((channel for channel in self.channels if channel.id == channel_id), None)

    def get_member(self, user_id):
        return next((member for member in self.members if member.id == user_id), None)

    async def fetch_member(self, user_id):
        member = self.get_member(user_id)
        if member is None:
            raise http_error(discord.NotFound, 404)
        return member


class FakeResponse:
    async def defer(self, **kwargs):
        pass


class FakeInteraction:
    """A click by user on a button of message (None for a reply to the click that is not a message edit)."""

    def __init__(self, user, guild, custom_id, message=None, edit_fails=False):
        self.user, self.guild, self.message, self.edit_fails = user, guild, message, edit_fails
        self.data = {"custom_id": custom_id}
        self.client = SimpleNamespace(settings=SETTINGS)
        self.response = FakeResponse()
        self.followup = SimpleNamespace(send=self._reply)
        self.replies = []

    async def _reply(self, content, ephemeral=False):
        self.replies.append((content, ephemeral))

    async def edit_original_response(self, content, view, allowed_mentions=None):
        if self.edit_fails:
            raise http_error(discord.NotFound, 404)
        self.message.content, self.message.view = content, view


def buttons(view):
    """(label, custom_id) of each button on the view, as Discord gets it."""
    return [(button["label"], button["custom_id"]) for row in view.to_components() for button in row["components"]]


class FakeCategoryChannel(FakeChannel):
    """A channel in the CTF's category, with its own overwrites until it is synced to the category's."""

    def __init__(self, name, category, overwrites):
        super().__init__(name)
        self.category, self.overwrites = category, overwrites

    async def edit(self, sync_permissions=False):
        if sync_permissions:
            self.overwrites = dict(self.category.overwrites)


class FakeCategory:
    def __init__(self, overwrites):
        self.id, self.overwrites, self.channels, self.edits = 1, overwrites, [], 0

    async def edit(self, overwrites):
        self.edits += 1
        self.overwrites = overwrites


class LocatedChannel:
    """A text channel, in the category with category_id (None when it is in no category)."""

    def __init__(self, category_id, channel_id=None):
        self.id = next(_ids) if channel_id is None else channel_id
        self.category_id = category_id


class LocatedThread:
    def __init__(self, parent):
        self.id, self.parent = next(_ids), parent
        self.category_id = parent.category_id


def fake_message(text, type=discord.MessageType.default):
    """A message as the archiver reads it."""
    author = SimpleNamespace(
        display_avatar=SimpleNamespace(url="https://example.com/avatar.png"),
        display_name="alice",
        name="alice",
        color="#ffffff",
        bot=False,
    )
    return SimpleNamespace(
        id=next(_ids),
        type=type,
        author=author,
        created_at=utc(2026, 10, 15, 12),
        edited_at=None,
        content=text,
        clean_content=text,
        system_content=text,
        attachments=[],
        interaction=None,
        reference=None,
        pinned=False,
        stickers=[],
        reactions=[],
    )


class FakeHistory:
    """Something with messages, as the archiver reads it: a channel or a thread."""

    def __init__(self, id, name, texts):
        self.id, self.name = id, name
        self.messages = [fake_message(text) for text in texts]

    async def history(self, limit=100, oldest_first=False):
        for message in self.messages:
            yield message


class FakeArchivedChannel(FakeHistory):
    """A channel in the CTF's category with its messages, and its active and archived threads."""

    def __init__(self, guild, name, texts):
        super().__init__(guild.channel_ids.pop(0), name, texts)
        self.threads, self.archived = [], {False: [], True: []}

    def thread(self, name, texts, archived=False, private=False, on=None):
        """A thread named name with the texts as its messages, made on the message with the text on (or on none).

        As Discord does: a thread made on a message has that message's ID, and starts with a reference to it."""
        if on is None:
            thread = FakeHistory(next(_ids), name, texts)
        else:
            starter = next(message for message in self.messages if message.content == on)
            thread = FakeHistory(starter.id, name, texts)
            thread.messages.insert(0, fake_message("", type=discord.MessageType.thread_starter_message))
        (self.archived[private] if archived else self.threads).append(thread)
        return thread

    async def archived_threads(self, private=False, limit=100):
        for thread in self.archived[private]:
            yield thread


class FakeCtftime:
    """get_event answering from events (an id missing from it is a 404), raising CtftimeError for the ids in broken."""

    def __init__(self, events=None, broken=()):
        self.events = events or {}
        self.broken = set(broken)
        self.asked = []

    async def get_event(self, event_id):
        self.asked.append(event_id)
        if event_id in self.broken:
            raise CtftimeError(f"CTFtime is down for {event_id}")
        return self.events.get(event_id)


class PinnableMessage:
    def __init__(self, channel, content):
        self.channel, self.id, self.content, self.pinned = channel, next(_ids), content, False

    async def pin(self):
        if self.channel.fail:
            raise discord.HTTPException(_NotFoundResponse(), "Maximum number of pins reached")
        self.pinned = True


class PinnablePartialMessage:
    def __init__(self, channel, message_id):
        self.channel, self.id = channel, message_id

    async def edit(self, content):
        message = next((message for message in self.channel.messages if message.id == self.id), None)
        if message is None:
            raise discord.NotFound(_NotFoundResponse(), "Unknown Message")
        if self.channel.fail:
            raise discord.HTTPException(_NotFoundResponse(), "Missing Permissions")
        message.content = content
        return message


class _NotFoundResponse:
    status, reason = 404, "Not Found"


class PinningChannel:
    """The main channel of a CTF, where the challenge overview is pinned; `fail` makes Discord refuse edits and pins."""

    def __init__(self, channel_id):
        self.id, self.messages, self.fail = channel_id, [], False

    async def send(self, content, allowed_mentions):
        self.messages.append(PinnableMessage(self, content))
        return self.messages[-1]

    def get_partial_message(self, message_id):
        return PinnablePartialMessage(self, message_id)
