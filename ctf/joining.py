"""Who plays a CTF: joining with the Join button, leaving with the Leave button, staff adding and removing players, and
closing joining once the CTF is released."""

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum, auto
from typing import cast

import discord

from core.settings import Roles
from ctf import store
from ctf.approval import close_card, post_card
from ctf.buttons import join_view
from ctf.join_message import refresh_join_message
from ctf.models import Ctf, PlayerStatus


class JoinOutcome(Enum):
    JOINED = auto()
    ALREADY_JOINED = auto()
    # Waiting for a moderator: an approval card was posted
    PENDING = auto()
    STILL_PENDING = auto()
    NO_PLAYER_ROLE = auto()
    CLOSED = auto()
    CTF_GONE = auto()
    ROLE_GONE = auto()
    BOT_CHANNEL_GONE = auto()


@dataclass(frozen=True)
class JoinResult:
    outcome: JoinOutcome
    ctf: Ctf | None


def join_outcome(role_names: set[str], roles: Roles, status: PlayerStatus | None, closed: bool) -> JoinOutcome:
    """What clicking Join does for someone with these roles; `status` is where they are on the player list, if at
    all."""
    if status is PlayerStatus.JOINED:
        return JoinOutcome.ALREADY_JOINED
    if closed:
        return JoinOutcome.CLOSED
    if status is PlayerStatus.PENDING:
        return JoinOutcome.STILL_PENDING
    if roles.trusted_players & role_names:
        return JoinOutcome.JOINED
    if roles.player is not None and roles.player in role_names:
        return JoinOutcome.PENDING
    return JoinOutcome.NO_PLAYER_ROLE


async def join(guild: discord.Guild, member: discord.Member, ctf_id: int, roles: Roles) -> JoinResult:
    ctf = store.get(ctf_id)
    if ctf is None:
        return JoinResult(JoinOutcome.CTF_GONE, None)

    entry = store.player(ctf.id, member.id)
    status = None if entry is None else entry.status
    outcome = join_outcome({role.name for role in member.roles}, roles, status, ctf.joining_closed)
    if outcome is JoinOutcome.JOINED:
        outcome = await _let_in(guild, member, ctf)
    elif outcome is JoinOutcome.PENDING:
        outcome = await _ask_moderators(guild, member, ctf, roles)
    return JoinResult(outcome, ctf)


async def _let_in(guild: discord.Guild, member: discord.Member, ctf: Ctf) -> JoinOutcome:
    role = guild.get_role(ctf.role_id)
    if role is None:
        return JoinOutcome.ROLE_GONE

    # On the list before the first await, so a second click right after is told they are playing already
    store.add_player(ctf.id, member.id, datetime.now(UTC))
    try:
        await member.add_roles(role)
    except BaseException:
        store.remove_player(ctf.id, member.id)
        raise
    await refresh_join_message(guild, ctf)
    return JoinOutcome.JOINED


async def _ask_moderators(guild: discord.Guild, member: discord.Member, ctf: Ctf, roles: Roles) -> JoinOutcome:
    bot_channel = cast(discord.TextChannel | None, guild.get_channel(ctf.bot_channel_id))
    if bot_channel is None:
        return JoinOutcome.BOT_CHANNEL_GONE

    # Pending before the first await, so a second click right after posts no second card
    try:
        store.add_pending_player(ctf.id, member.id, datetime.now(UTC))
    except sqlite3.IntegrityError:
        return JoinOutcome.STILL_PENDING
    try:
        card = await post_card(guild, bot_channel, member, ctf, roles)
    except BaseException:
        store.remove_player(ctf.id, member.id)
        raise
    if not store.set_approval_card(ctf.id, member.id, card.id) and store.reread(ctf.id).joining_closed:
        # Released while the card was posted, after its pending players were taken off the list
        await close_card(bot_channel, card.id)
        return JoinOutcome.CLOSED
    return JoinOutcome.PENDING


async def leave(guild: discord.Guild, member: discord.Member, ctf_id: int) -> Ctf | None:
    """Returns the CTF left, or None when the member was not on its player list."""
    ctf = store.get(ctf_id)
    if ctf is None or store.player(ctf.id, member.id) is None:
        return None
    await remove_player(guild, member, ctf)
    return ctf


async def add_player(guild: discord.Guild, member: discord.Member, ctf: Ctf) -> bool:
    """Returns False when the CTF's role no longer exists."""
    role = guild.get_role(ctf.role_id)
    if role is None:
        return False
    await member.add_roles(role)
    store.add_player(ctf.id, member.id, datetime.now(UTC))
    await refresh_join_message(guild, ctf)
    return True


async def remove_player(guild: discord.Guild, member: discord.Member, ctf: Ctf) -> None:
    role = guild.get_role(ctf.role_id)
    if role is not None:
        await member.remove_roles(role)
    store.remove_player(ctf.id, member.id)
    await refresh_join_message(guild, ctf)


async def close_joining(guild: discord.Guild, ctf: Ctf) -> None:
    """Disable the Join button, and close the approval cards of everyone still waiting: they are taken off the player
    list and their cards lose their buttons."""
    pending = [player for player in store.players(ctf.id) if player.status is PlayerStatus.PENDING]
    # Off the list before the first await, so a click on one of their cards meanwhile is told it was already handled
    for player in pending:
        store.remove_player(ctf.id, player.user_id)

    await refresh_join_message(guild, ctf, view=join_view(ctf.id, disabled=True))

    bot_channel = cast(discord.TextChannel | None, guild.get_channel(ctf.bot_channel_id))
    for player in pending:
        if player.approval_card_message_id is not None and bot_channel is not None:
            await close_card(bot_channel, player.approval_card_message_id)
