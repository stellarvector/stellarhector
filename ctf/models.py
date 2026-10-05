"""The CTFs the bot manages, as stored in the database (see ctf/store.py)."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


@dataclass(frozen=True)
class NewCtf:
    """A CTF whose Discord objects were just created and that is not stored yet."""

    name: str
    ctftime_id: int | None
    start: datetime | None
    finish: datetime | None
    role_id: int
    category_id: int
    main_channel_id: int
    bot_channel_id: int
    guide_message_id: int


class Stage(Enum):
    SET_UP = "set up"
    RELEASED = "released"
    LOCKED = "locked"
    ARCHIVED = "archived"
    REMOVED = "removed"


@dataclass(frozen=True)
class Ctf(NewCtf):
    id: int
    # Where the join message is; None when it was never posted
    join_channel_id: int | None
    join_message_id: int | None
    # The challenge overview in the main channel; None until the first challenge
    overview_message_id: int | None
    # When each lifecycle step was done; None until it is
    last_call_at: datetime | None
    released_at: datetime | None
    locked_at: datetime | None
    archived_at: datetime | None
    removal_reminded_at: datetime | None
    removed_at: datetime | None

    @property
    def stage(self) -> Stage:
        # /archive-ctf can archive a CTF before it is locked
        for at, stage in [
            (self.removed_at, Stage.REMOVED),
            (self.archived_at, Stage.ARCHIVED),
            (self.locked_at, Stage.LOCKED),
            (self.released_at, Stage.RELEASED),
        ]:
            if at is not None:
                return stage
        return Stage.SET_UP

    @property
    def joining_closed(self) -> bool:
        return self.stage is not Stage.SET_UP


class PlayerStatus(Enum):
    JOINED = "joined"
    # Waiting for a moderator to decide on their approval card
    PENDING = "pending"


@dataclass(frozen=True)
class Player:
    user_id: int
    status: PlayerStatus
    approval_card_message_id: int | None
    joined_at: datetime


@dataclass(frozen=True)
class Category:
    # Also the name of the category's channel
    slug: str
    channel_id: int


@dataclass(frozen=True)
class Challenge:
    category: str
    slug: str
    thread_id: int
    solved: bool
