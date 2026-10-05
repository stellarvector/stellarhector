"""Building the values tests need: times, CTFs, settings and an empty database."""

import tempfile
import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from core import db
from core.settings import Settings
from ctf.models import Ctf, NewCtf

SETTINGS = Settings.from_env(
    {
        "BOT_TOKEN": "token",
        "GUILD_ID": "123",
        "ADMIN_ROLE": "sv{admin}",
        "MANAGER_ROLE": "sv{manager}",
        "MODERATOR_ROLE": "sv{moderator}",
        "CORE_PLAYER_ROLE": "sv{core-player}",
        "KNOWN_PLAYER_ROLE": "sv{known-player}",
        "PLAYER_ROLE": "sv{player}",
        "FOLLOWER_ROLE": "sv{follower}",
        "CTF_ROLE_COLOR_HEX": "0x00ff00",
    }
)
ROLES = SETTINGS.roles


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


def new_ctf(
    name="Foo CTF",
    ctftime_id=None,
    start=None,
    finish=None,
    role_id=1,
    category_id=2,
    main_channel_id=3,
    bot_channel_id=4,
    guide_message_id=5,
):
    return NewCtf(
        name=name,
        ctftime_id=ctftime_id,
        start=start,
        finish=finish,
        role_id=role_id,
        category_id=category_id,
        main_channel_id=main_channel_id,
        bot_channel_id=bot_channel_id,
        guide_message_id=guide_message_id,
    )


def use_temporary_database(test: unittest.TestCase) -> Path:
    """Give the test an empty database of its own, closed again after it."""
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    path = Path(tmp.name) / "test.db"
    db.init(path)
    test.addCleanup(db.close)
    return path


# The dates of the CTF stored_ctf makes, and when its automatic steps are due
START, FINISH = utc(2026, 10, 10, 8), utc(2026, 10, 12, 18)
LAST_CALL, RELEASE, LOCK = START - timedelta(days=1), FINISH + timedelta(days=1), FINISH + timedelta(days=5)
REMOVAL_REMINDER = LOCK + timedelta(weeks=4)


def stored_ctf(**changes):
    """A stored CTF on CTFtime, running from START to FINISH, with no lifecycle steps done."""
    stored = Ctf(
        name="Foo CTF",
        ctftime_id=3352,
        start=START,
        finish=FINISH,
        role_id=1,
        category_id=2,
        main_channel_id=3,
        bot_channel_id=4,
        guide_message_id=5,
        id=1,
        join_channel_id=None,
        join_message_id=None,
        overview_message_id=None,
        last_call_at=None,
        released_at=None,
        locked_at=None,
        archived_at=None,
        removal_reminded_at=None,
        removed_at=None,
    )
    return replace(stored, **changes)
