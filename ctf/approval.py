"""Approval cards: a player without a trusted role who clicks Join gets a card in the CTF's #bot, and staff accept or
decline them there."""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum, auto
from typing import cast

import discord

from core.settings import Roles
from ctf import store
from ctf.buttons import Decision, approval_view
from ctf.join_message import refresh_join_message
from ctf.models import Ctf, Player, PlayerStatus
from utils import discord_objects

log = logging.getLogger("bot")

CARD_CLOSED = ":lock: No longer needed: CTF released"


class RequestRefusal(Enum):
    NOT_STAFF = auto()
    CTF_GONE = auto()
    MEMBER_LEFT = auto()
    ROLE_GONE = auto()
    ALREADY_HANDLED = auto()


@dataclass(frozen=True)
class Decided:
    # What went wrong while carrying out the decision, shown on the card
    problem: str | None


def approval_card(
    ctf_name: str, user_id: int, role_ids: list[int], joined_server_at: datetime | None, times_joined: int
) -> str:
    roles = ", ".join(f"<@&{role_id}>" for role_id in role_ids) or "none"
    if joined_server_at is None:
        since = "unknown"
    else:
        timestamp = int(joined_server_at.timestamp())
        since = f"<t:{timestamp}:D> (<t:{timestamp}:R>)"
    return "\n".join(
        [
            f":raising_hand: <@{user_id}> wants to join **{discord.utils.escape_markdown(ctf_name)}**",
            f"**Roles:** {roles}",
            f"**On the server since:** {since}",
            f"**CTFs joined before:** {times_joined}",
        ]
    )


def decision_line(decision: Decision, moderator_id: int, problem: str | None = None) -> str:
    line = {
        Decision.ACCEPT: f":white_check_mark: Accepted by <@{moderator_id}>",
        Decision.ACCEPT_KNOWN: f":white_check_mark: Accepted as known player by <@{moderator_id}>",
        Decision.DECLINE: f":x: Declined by <@{moderator_id}>",
    }[decision]
    return line if problem is None else f"{line} ({problem})"


async def post_card(
    guild: discord.Guild, bot_channel: discord.TextChannel, member: discord.Member, ctf: Ctf, roles: Roles
) -> discord.Message:
    member_roles = sorted(
        (role for role in member.roles if role != guild.default_role), key=lambda role: role.position, reverse=True
    )
    return await bot_channel.send(
        approval_card(
            ctf.name, member.id, [role.id for role in member_roles], member.joined_at, store.times_joined(member.id)
        ),
        view=approval_view(ctf.id, member.id, offer_known_player=roles.known_player is not None),
        allowed_mentions=discord.AllowedMentions.none(),
    )


async def close_card(channel: discord.TextChannel, message_id: int) -> None:
    try:
        card = await channel.fetch_message(message_id)
        await card.edit(
            content=f"{card.content}\n{CARD_CLOSED}", view=None, allowed_mentions=discord.AllowedMentions.none()
        )
    except discord.NotFound:
        pass
    except discord.HTTPException:
        log.exception(f"Could not close approval card {message_id}, remove its buttons by hand")


async def decide_request(
    guild: discord.Guild,
    moderator: discord.Member,
    decision: Decision,
    ctf_id: int,
    user_id: int,
    card_id: int,
    roles: Roles,
) -> RequestRefusal | Decided:
    if not roles.staff & {role.name for role in moderator.roles}:
        return RequestRefusal.NOT_STAFF

    ctf = store.get(ctf_id)
    if ctf is None:
        return RequestRefusal.CTF_GONE

    member = await discord_objects.member(guild, user_id)
    ctf_role = guild.get_role(ctf.role_id)
    if decision is not Decision.DECLINE:
        if member is None:
            return RequestRefusal.MEMBER_LEFT
        if ctf_role is None:
            return RequestRefusal.ROLE_GONE

    # Checked and settled before the next await, so a second click on the card is told it was already handled
    entry = store.player(ctf.id, user_id)
    if entry is None or entry.status is not PlayerStatus.PENDING or entry.approval_card_message_id != card_id:
        return RequestRefusal.ALREADY_HANDLED

    if decision is Decision.DECLINE:
        store.remove_player(ctf.id, user_id)
        if member is None:
            return Decided("left the server")
        return Decided(None if await _send_decline(member, ctf) else "DM failed")

    assert member is not None and ctf_role is not None
    return Decided(await _accept(guild, member, ctf, ctf_role, entry, decision, roles))


async def _accept(
    guild: discord.Guild,
    member: discord.Member,
    ctf: Ctf,
    ctf_role: discord.Role,
    entry: Player,
    decision: Decision,
    roles: Roles,
) -> str | None:
    """Give the member the CTF role (and the known-player role for ACCEPT_KNOWN). Returns what went wrong, if
    anything, for the card."""
    new_roles, problem = [ctf_role], None
    if decision is Decision.ACCEPT_KNOWN:
        known = discord.utils.get(guild.roles, name=roles.known_player)
        if known is None:
            problem = "known-player role not found"
        else:
            new_roles.append(known)

    store.add_player(ctf.id, member.id, datetime.now(UTC))
    try:
        await member.add_roles(*new_roles)
    except BaseException:
        if store.reread(ctf.id).joining_closed:
            # Released meanwhile, which closed the card
            store.remove_player(ctf.id, member.id)
        else:
            # Back to waiting on this card, so the decision can be retried
            store.reopen_request(ctf.id, member.id, entry.joined_at, cast(int, entry.approval_card_message_id))
        raise
    await refresh_join_message(guild, ctf)
    return problem


async def _send_decline(member: discord.Member, ctf: Ctf) -> bool:
    try:
        await member.send(
            f"For now it was not possible to join **{discord.utils.escape_markdown(ctf.name)}**, "
            f"go see a moderator on-site."
        )
    except discord.HTTPException:
        return False
    return True
