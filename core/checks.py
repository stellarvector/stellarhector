"""App command checks on the role names in the bot's settings. The settings are read when the command runs."""

from collections.abc import Callable
from typing import Protocol, TypeVar, cast

import discord
from discord import app_commands

from core.settings import Roles, Settings

T = TypeVar("T")


class _HasSettings(Protocol):
    settings: Settings


def _has_role_in(group: Callable[[Roles], frozenset[str]]) -> Callable[[T], T]:
    async def predicate(interaction: discord.Interaction) -> bool:
        names = group(cast(_HasSettings, interaction.client).settings.roles)
        roles = getattr(interaction.user, "roles", [])
        if any(role.name in names for role in roles):
            return True
        raise app_commands.MissingAnyRole(sorted(names))

    return app_commands.check(predicate)


def admins_only() -> Callable[[T], T]:
    return _has_role_in(lambda roles: roles.admins)


def managers_only() -> Callable[[T], T]:
    return _has_role_in(lambda roles: roles.managers)


def staff_only() -> Callable[[T], T]:
    return _has_role_in(lambda roles: roles.staff)
