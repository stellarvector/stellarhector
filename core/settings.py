"""The bot's settings, read once from .env at startup (see .env.example for every key).

Optional settings that are unset or invalid fall back to a default with a warning, so a typo switches a feature off
instead of crashing the bot; only BOT_TOKEN and GUILD_ID are required.
"""

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import dotenv_values

from core.scheduler import DEFAULT_WATCHDOG_LIMIT, TICK_INTERVAL

log = logging.getLogger("bot")

DEFAULT_TIMEZONE = "Europe/Brussels"
DEFAULT_DATABASE_PATH = "./data/stellarhector.db"
DEFAULT_ROLE_COLOR = 0x00FF00
DEFAULT_ICS_POLL_MINUTES = 15
DEFAULT_ICS_LOOKAHEAD_DAYS = 30

Env = Mapping[str, str | None]


class SettingsError(ValueError):
    """A required setting is missing or invalid; the bot can't start without it."""


@dataclass(frozen=True)
class Roles:
    """The names of the server's roles. A role that isn't configured is None."""

    admin: str | None = None
    manager: str | None = None
    moderator: str | None = None
    core_player: str | None = None
    known_player: str | None = None
    # Onboarding gives every team member one of these two
    player: str | None = None
    follower: str | None = None

    @property
    def admins(self) -> frozenset[str]:
        return _names(self.admin)

    @property
    def managers(self) -> frozenset[str]:
        """Admins and managers, who run the CTF management commands."""
        return _names(self.admin, self.manager)

    @property
    def staff(self) -> frozenset[str]:
        """Admins, managers and moderators."""
        return _names(self.admin, self.manager, self.moderator)

    @property
    def members(self) -> frozenset[str]:
        """Every member of the team: players and followers. A released CTF is opened to them."""
        return _names(self.player, self.follower)

    @property
    def trusted_players(self) -> frozenset[str]:
        """The roles whose members join a CTF right away with its Join button, without waiting for a moderator."""
        return _names(self.core_player, self.known_player) | self.staff


@dataclass(frozen=True)
class Channels:
    """The IDs of the server-wide channels. A feature whose channel is None is switched off."""

    admin: int | None = None
    ctf_selection: int | None = None
    upcoming_ctfs: int | None = None
    calendar: int | None = None
    learning_forum: int | None = None


# The .env key of each Channels field
CHANNEL_KEYS = {
    "admin": "ADMIN_CHANNEL_ID",
    "ctf_selection": "CTF_SELECTION_CHANNEL_ID",
    "upcoming_ctfs": "UPCOMING_CTFS_CHANNEL_ID",
    "calendar": "CALENDAR_CHANNEL_ID",
    "learning_forum": "LEARNING_FORUM_ID",
}


@dataclass(frozen=True)
class ArchiveSettings:
    """Where the archive repository is checked out and cloned from, and whether archiving commits and pushes it."""

    local_path: Path
    remote_url: str | None = None
    commit: bool = False
    push: bool = False


@dataclass(frozen=True)
class CalendarSettings:
    """The ICS calendar feed that is mirrored into Discord events. It is switched off when `ics_url` is None."""

    ics_url: str | None = None
    poll_minutes: int = DEFAULT_ICS_POLL_MINUTES
    lookahead: timedelta = timedelta(days=DEFAULT_ICS_LOOKAHEAD_DAYS)
    # The name of the role mentioned in announcements; None pings nobody
    ping_role: str | None = None


@dataclass(frozen=True)
class Settings:
    bot_token: str
    guild_id: int
    roles: Roles
    channels: Channels
    archive: ArchiveSettings
    calendar: CalendarSettings
    timezone: str = DEFAULT_TIMEZONE
    ctf_role_color: int = DEFAULT_ROLE_COLOR
    database_path: str = DEFAULT_DATABASE_PATH
    log_file: str | None = None
    watchdog_limit: timedelta = DEFAULT_WATCHDOG_LIMIT

    @classmethod
    def from_env(cls, env: Env) -> "Settings":
        """Read the settings from `env`, the key-value pairs of .env. Raises SettingsError when a required setting is
        missing."""
        guild_id = channel_id(env, "GUILD_ID")
        if guild_id is None:
            raise SettingsError("GUILD_ID must be set to the ID of the server")
        bot_token = _text(env, "BOT_TOKEN")
        if bot_token is None:
            raise SettingsError("BOT_TOKEN must be set")

        return cls(
            bot_token=bot_token,
            guild_id=guild_id,
            roles=Roles(
                admin=_text(env, "ADMIN_ROLE"),
                manager=_text(env, "MANAGER_ROLE"),
                moderator=_text(env, "MODERATOR_ROLE"),
                core_player=_text(env, "CORE_PLAYER_ROLE"),
                known_player=_text(env, "KNOWN_PLAYER_ROLE"),
                player=_text(env, "PLAYER_ROLE"),
                follower=_text(env, "FOLLOWER_ROLE"),
            ),
            channels=Channels(**{field: channel_id(env, key) for field, key in CHANNEL_KEYS.items()}),
            archive=ArchiveSettings(
                local_path=Path(_text(env, "ARCHIVE_LOCAL_PATH") or "./data/archive"),
                remote_url=_text(env, "ARCHIVE_REMOTE_URL"),
                commit=flag(env, "SHOULD_COMMIT"),
                push=flag(env, "SHOULD_PUSH"),
            ),
            calendar=CalendarSettings(
                ics_url=_text(env, "ICS_URL"),
                poll_minutes=positive_int(env, "ICS_POLL_MINUTES", DEFAULT_ICS_POLL_MINUTES),
                lookahead=timedelta(days=positive_int(env, "ICS_LOOKAHEAD_DAYS", DEFAULT_ICS_LOOKAHEAD_DAYS)),
                ping_role=_text(env, "ICS_PING_ROLE"),
            ),
            timezone=timezone(env),
            ctf_role_color=color(env, "CTF_ROLE_COLOR_HEX", DEFAULT_ROLE_COLOR),
            database_path=_text(env, "DATABASE_PATH") or DEFAULT_DATABASE_PATH,
            log_file=cls.log_file_in(env),
            watchdog_limit=watchdog_limit(env, DEFAULT_WATCHDOG_LIMIT, TICK_INTERVAL),
        )

    @staticmethod
    def log_file_in(env: Env) -> str | None:
        # LOG_FILE is read on its own, so logging can start before the other settings are read and warned about
        return _text(env, "LOG_FILE")

    def warn_switched_off(self) -> None:
        for field, key in CHANNEL_KEYS.items():
            if getattr(self.channels, field) is None:
                log.warning(f"{key} is not configured, the feature using it is switched off")


def read_env(path: str = ".env") -> Env:
    return dotenv_values(path)


def _names(*names: str | None) -> frozenset[str]:
    return frozenset(name for name in names if name)


def _text(env: Env, key: str) -> str | None:
    """The stripped value of `key`, or None when it is unset or blank."""
    return (env.get(key) or "").strip() or None


def channel_id(env: Env, key: str) -> int | None:
    """The Discord ID in `key`, or None when it is unset or not a number, which switches off the feature using it."""
    value = _text(env, key)
    if value is None:
        return None
    if not value.isdigit():
        log.warning(f"{key} is not a valid ID ({value!r}), treating it as unset")
        return None
    return int(value)


def positive_int(env: Env, key: str, default: int) -> int:
    """The whole number above zero in `key`, or `default` when it is unset or invalid."""
    value = _text(env, key)
    if value is None:
        return default
    if not value.isdigit() or int(value) == 0:
        log.warning(f"{key} {value!r} must be a whole number above 0, using {default}")
        return default
    return int(value)


def flag(env: Env, key: str) -> bool:
    """A number other than 0, "true" or "yes" switches `key` on. Any other value, or none, leaves it off."""
    value = _text(env, key)
    if value is None:
        return False
    if value.isdigit():
        return int(value) != 0
    if value.lower() in ("true", "yes"):
        return True
    if value.lower() not in ("false", "no"):
        log.warning(f"{key} {value!r} must be 1 or 0, treating it as 0")
    return False


def color(env: Env, key: str, default: int) -> int:
    """The hexadecimal color in `key`, written as 0x00ff00 or 00ff00, or `default` when it is unset or invalid."""
    value = _text(env, key)
    if value is None:
        return default
    try:
        parsed = int(value, 16)
    except ValueError:
        parsed = -1
    if not 0 <= parsed <= 0xFFFFFF:
        log.warning(f"{key} {value!r} is not a hexadecimal color, using {default:#08x}")
        return default
    return parsed


def timezone(env: Env) -> str:
    value = _text(env, "TIMEZONE")
    if value is None:
        return DEFAULT_TIMEZONE
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        log.warning(f"TIMEZONE {value!r} is unknown, using {DEFAULT_TIMEZONE}")
        return DEFAULT_TIMEZONE
    return value


def watchdog_limit(env: Env, default: timedelta, longer_than: timedelta) -> timedelta:
    """WATCHDOG_TIMEOUT_MINUTES as a timedelta, or `default` when it is unset, not a number, or not longer than
    `longer_than`."""
    value = _text(env, "WATCHDOG_TIMEOUT_MINUTES")
    if value is None:
        return default
    if not value.isdigit() or timedelta(minutes=int(value)) <= longer_than:
        log.warning(
            f"WATCHDOG_TIMEOUT_MINUTES {value!r} must be a number of minutes above {longer_than}, using {default}"
        )
        return default
    return timedelta(minutes=int(value))
