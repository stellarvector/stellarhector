"""Signing up for a CTF: the join message in #upcoming-ctfs with its Join button, the approval cards in the CTF's #bot
on which staff let plain players in, and the Leave button on the guide in the CTF's main channel.

decide, join_message, approval_card and decision_line are pure: who may join how, and what the join message and the
cards say. The buttons keep working after a restart: their custom_id holds the CTF's ID, and register makes the bot
handle them for every CTF.
"""
import asyncio
import logging
from collections import defaultdict
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

import discord

from utils import ctfs, ctftime_check
from utils.text import cut

# How many players the join message names, and how many on-campus sessions it lists, to stay under 2000 characters
PLAYER_LIMIT = 20
SESSION_LIMIT = 5
SESSION_TITLE_LIMIT = 100


class Outcome(Enum):
    """What clicking Join does for someone."""
    JOINED = "joined"
    ALREADY_JOINED = "already joined"
    PENDING = "pending"
    STILL_PENDING = "still pending"
    NO_PLAYER_ROLE = "no player role"
    CLOSED = "closed"


class Decision(Enum):
    """What staff decide on an approval card; the value is part of the button's custom_id."""
    ACCEPT = "accept"
    ACCEPT_KNOWN = "known"
    DECLINE = "decline"


@dataclass(frozen=True)
class JoinRoles:
    """Names of the roles that let someone join: trusted ones (core and known players, staff) join right away, the
    player role (None when not configured) waits for a moderator."""
    trusted: frozenset[str]
    player: str | None


@dataclass(frozen=True)
class ApprovalRoles:
    """Names of the staff roles that may decide on approval cards, and of the known-player role that Accept + known
    player gives (None when not configured: that button is then left out)."""
    staff: frozenset[str]
    known_player: str | None


# The roles that let someone join, and those deciding on approval cards, set by register
_roles = None
_approval_roles = None
# Per CTF ID: two refreshes at once could edit its join message in the wrong order, the older list last
_refresh_locks = defaultdict(asyncio.Lock)

STILL_PENDING = "Still waiting for moderator confirmation"


def register(client, roles, approval_roles):
    """Handle the Join and Leave buttons of every CTF and the buttons on its approval cards from now on, letting people
    join with the JoinRoles roles and staff decide with the ApprovalRoles roles."""
    global _roles, _approval_roles

    _roles, _approval_roles = roles, approval_roles
    client.add_dynamic_items(JoinButton, LeaveButton, ApprovalButton)


def join_view(ctf_id):
    """The Join button of the CTF's join message."""
    return discord.ui.View(timeout=None).add_item(JoinButton(ctf_id))


def leave_view(ctf_id):
    """The Leave button of the guide in the CTF's main channel."""
    return discord.ui.View(timeout=None).add_item(LeaveButton(ctf_id))


def approval_view(ctf_id, user_id):
    """The buttons on the approval card for the user asking to join the CTF."""
    decisions = [decision for decision in Decision
                 if decision is not Decision.ACCEPT_KNOWN or _approval_roles.known_player is not None]
    view = discord.ui.View(timeout=None)
    for decision in decisions:
        view.add_item(ApprovalButton(decision, ctf_id, user_id))
    return view


def is_closed(ctf):
    """Whether joining the CTF is closed: it is released (open to all members) or locked, or further along."""
    return any(at is not None for at in (ctf.released_at, ctf.locked_at, ctf.archived_at, ctf.removed_at))


def decide(role_names, roles, status, closed):
    """The Outcome of a Join click by someone with these role names. status is theirs on the CTF's player list
    ("joined", "pending", or None when they are not on it); closed is whether joining the CTF is closed."""
    if status == "joined":
        return Outcome.ALREADY_JOINED
    if closed:
        return Outcome.CLOSED
    if status == "pending":
        return Outcome.STILL_PENDING
    if roles.trusted & set(role_names):
        return Outcome.JOINED
    if roles.player is not None and roles.player in role_names:
        return Outcome.PENDING
    return Outcome.NO_PLAYER_ROLE


def join_message(ctf, player_ids, sessions):
    """The join message of the CTF: its name, CTFtime link and dates, its on-campus sessions (ctftime_check.Sessions),
    and who plays (the user IDs of the joined players, in the order they joined)."""
    lines = [f"## :zap: {discord.utils.escape_markdown(ctf.name)}"]
    if ctf.ctftime_id is not None:
        lines.append(f"<https://ctftime.org/event/{ctf.ctftime_id}/>")
    if ctf.start is not None and ctf.finish is not None:
        lines.append(f"From {_period(ctf.start, ctf.finish)}")

    if sessions:
        lines.append("**On campus:**")
        for session in sorted(sessions, key=lambda session: session.start)[:SESSION_LIMIT]:
            title = discord.utils.escape_markdown(cut(session.title, SESSION_TITLE_LIMIT))
            lines.append(f"- {title}: {_period(session.start, session.end)}")
        if len(sessions) > SESSION_LIMIT:
            lines.append(f"- and {len(sessions) - SESSION_LIMIT} more")

    lines.append(_playing(player_ids))
    return "\n".join(lines)


def approval_card(ctf_name, user_id, role_ids, joined_server_at, times_joined):
    """The approval card for the user asking to join the CTF: their roles (IDs, top first), when they joined the server
    (None when unknown), and how many CTFs they have joined before."""
    roles = ", ".join(f"<@&{role_id}>" for role_id in role_ids) or "none"
    if joined_server_at is None:
        since = "unknown"
    else:
        timestamp = int(joined_server_at.timestamp())
        since = f"<t:{timestamp}:D> (<t:{timestamp}:R>)"
    return "\n".join([
        f":raising_hand: <@{user_id}> wants to join **{discord.utils.escape_markdown(ctf_name)}**",
        f"**Roles:** {roles}",
        f"**On the server since:** {since}",
        f"**CTFs joined before:** {times_joined}",
    ])


def decision_line(decision, moderator_id, problem=None):
    """The line added to an approval card once a moderator decided, with what went wrong (if anything)."""
    line = {
        Decision.ACCEPT: f":white_check_mark: Accepted by <@{moderator_id}>",
        Decision.ACCEPT_KNOWN: f":white_check_mark: Accepted as known player by <@{moderator_id}>",
        Decision.DECLINE: f":x: Declined by <@{moderator_id}>",
    }[decision]
    return line if problem is None else f"{line} ({problem})"


def _playing(player_ids):
    if not player_ids:
        return "**Playing:** nobody yet, click **Join** to be the first"

    names = ", ".join(f"<@{user_id}>" for user_id in player_ids[:PLAYER_LIMIT])
    more = f" and {len(player_ids) - PLAYER_LIMIT} more" if len(player_ids) > PLAYER_LIMIT else ""
    return f"**Playing ({len(player_ids)}):** {names}{more}"


def _period(start, end):
    return f"<t:{int(start.timestamp())}:F> to <t:{int(end.timestamp())}:F>"


async def refresh_join_message(guild, ctf):
    """Show the CTF's current player list and sessions on its join message, if it has one. A join message that can't
    be edited is logged: the player list itself is right, and the next refresh tries again."""
    if ctf.join_message_id is None:
        return

    channel = guild.get_channel(ctf.join_channel_id)
    if channel is None:
        logging.getLogger("bot").warning(f"The join message channel of CTF {ctf.name!r} no longer exists")
        return

    async with _refresh_locks[ctf.id]:
        try:
            await channel.get_partial_message(ctf.join_message_id).edit(
                content=current_join_message(ctf), allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            logging.getLogger("bot").exception(f"Could not update the join message of CTF {ctf.name!r}")


def current_join_message(ctf):
    """The CTF's join message as it should read now, with its current players and sessions."""
    return join_message(ctf, joined_ids(ctf.id), current_sessions(ctf, datetime.now(timezone.utc)))


def joined_ids(ctf_id):
    """The user IDs of who plays the CTF (not who waits for a moderator), in the order they joined."""
    return [player.user_id for player in ctfs.players(ctf_id) if player.status == "joined"]


def current_sessions(ctf, now):
    """The CTF's on-campus sessions that are not over at now: the calendar entries linking to its CTFtime event."""
    if ctf.ctftime_id is None:
        return []
    return [session for session in ctftime_check.linked_sessions().get(ctf.ctftime_id, []) if session.end > now]


class JoinButton(discord.ui.DynamicItem[discord.ui.Button], template=r"ctf:join:(?P<ctf_id>[0-9]+)"):
    """The Join button on a CTF's join message; it works for every CTF once register has run."""
    def __init__(self, ctf_id):
        super().__init__(discord.ui.Button(label="Join", style=discord.ButtonStyle.success,
                                           custom_id=f"ctf:join:{ctf_id}"))
        self.ctf_id = ctf_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["ctf_id"]))

    async def callback(self, interaction):
        await _answer(interaction, _join(interaction, self.ctf_id), thinking=True)


class LeaveButton(discord.ui.DynamicItem[discord.ui.Button], template=r"ctf:leave:(?P<ctf_id>[0-9]+)"):
    """The Leave button on the guide in a CTF's main channel; it works for every CTF once register has run."""
    def __init__(self, ctf_id):
        super().__init__(discord.ui.Button(label="Leave", style=discord.ButtonStyle.secondary,
                                           custom_id=f"ctf:leave:{ctf_id}"))
        self.ctf_id = ctf_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["ctf_id"]))

    async def callback(self, interaction):
        await _answer(interaction, _leave(interaction, self.ctf_id), thinking=True)


class ApprovalButton(discord.ui.DynamicItem[discord.ui.Button],
                     template=r"ctf:card:(?P<decision>accept|known|decline):(?P<ctf_id>[0-9]+):(?P<user_id>[0-9]+)"):
    """A button on an approval card: staff accept or decline the user asking to join the CTF. It works for every card
    once register has run."""
    BUTTONS = {Decision.ACCEPT: ("Accept", discord.ButtonStyle.success),
              Decision.ACCEPT_KNOWN: ("Accept + known player", discord.ButtonStyle.primary),
              Decision.DECLINE: ("Decline", discord.ButtonStyle.danger)}

    def __init__(self, decision, ctf_id, user_id):
        label, style = self.BUTTONS[decision]
        super().__init__(discord.ui.Button(label=label, style=style,
                                           custom_id=f"ctf:card:{decision.value}:{ctf_id}:{user_id}"))
        self.decision, self.ctf_id, self.user_id = decision, ctf_id, user_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(Decision(match["decision"]), int(match["ctf_id"]), int(match["user_id"]))

    async def callback(self, interaction):
        # Not thinking: the click is acknowledged as an update of the card, which _decide edits
        await _answer(interaction, _decide(interaction, self.decision, self.ctf_id, self.user_id), thinking=False)


async def _answer(interaction, work, thinking):
    """Run work, a coroutine giving the reply (None for none), and send that reply only to the one who clicked. While
    thinking, the clicker sees the bot is busy; otherwise the click is acknowledged as an update of its message."""
    if thinking:
        await interaction.response.defer(ephemeral=True, thinking=True)
    else:
        await interaction.response.defer()
    try:
        reply = await work
    except Exception:
        logging.getLogger("bot").exception(f"Handling a click on {interaction.data.get('custom_id')} failed")
        reply = "Sorry, an unknown error occurred, please ask a moderator for help."
    if reply is not None:
        await interaction.followup.send(reply, ephemeral=True)


async def _join(interaction, ctf_id):
    member, guild = interaction.user, interaction.guild
    ctf = ctfs.get(ctf_id)
    if ctf is None:
        return ":no_entry: This CTF no longer exists."

    entry = ctfs.player(ctf.id, member.id)
    outcome = decide({role.name for role in member.roles}, _roles, entry and entry.status, is_closed(ctf))
    main = f"<#{ctf.main_channel_id}>"
    name = discord.utils.escape_markdown(ctf.name)

    if outcome is Outcome.JOINED:
        return await _let_in(guild, member, ctf, main)
    if outcome is Outcome.PENDING:
        return await _ask_moderators(guild, member, ctf)
    return {
        Outcome.ALREADY_JOINED: f"You're already playing, see {main}",
        Outcome.STILL_PENDING: STILL_PENDING,
        Outcome.NO_PLAYER_ROLE: f"You can't join **{name}** this way, ask a moderator to add you.",
        Outcome.CLOSED: f":no_entry: Joining **{name}** is closed.",
    }[outcome]


async def _let_in(guild, member, ctf, main):
    role = guild.get_role(ctf.role_id)
    if role is None:
        return ":no_entry: The role of this CTF no longer exists, ask a moderator."

    # On the list before the first await, so a second click right after is told they are playing already
    ctfs.add_player(ctf.id, member.id, datetime.now(timezone.utc))
    try:
        await member.add_roles(role)
    except BaseException:
        ctfs.remove_player(ctf.id, member.id)
        raise
    await refresh_join_message(guild, ctf)
    return f"You're in, see {main}"


async def _ask_moderators(guild, member, ctf):
    bot_channel = guild.get_channel(ctf.bot_channel_id)
    if bot_channel is None:
        return ":no_entry: The #bot channel of this CTF no longer exists, ask a moderator."

    # Pending before the first await, so a second click right after posts no second card
    try:
        ctfs.add_pending_player(ctf.id, member.id, datetime.now(timezone.utc))
    except sqlite3.IntegrityError:
        return STILL_PENDING
    try:
        roles = sorted((role for role in member.roles if role != guild.default_role),
                       key=lambda role: role.position, reverse=True)
        card = await bot_channel.send(
            approval_card(ctf.name, member.id, [role.id for role in roles], member.joined_at,
                          ctfs.times_joined(member.id)),
            view=approval_view(ctf.id, member.id), allowed_mentions=discord.AllowedMentions.none())
    except BaseException:
        ctfs.remove_player(ctf.id, member.id)
        raise
    ctfs.set_approval_card(ctf.id, member.id, card.id)
    return "Waiting for moderator confirmation"


async def _leave(interaction, ctf_id):
    member, guild = interaction.user, interaction.guild
    ctf = ctfs.get(ctf_id)
    if ctf is None or ctfs.player(ctf.id, member.id) is None:
        return "You're not on the player list of this CTF, there is nothing to leave."

    role = guild.get_role(ctf.role_id)
    if role is not None:
        await member.remove_roles(role)
    ctfs.remove_player(ctf.id, member.id)
    await refresh_join_message(guild, ctf)
    return f"You left **{discord.utils.escape_markdown(ctf.name)}**"


async def _decide(interaction, decision, ctf_id, user_id):
    """Carry out the staff member's decision on the approval card for the user asking to join the CTF, and mark it on
    the card. Returns the reply only the clicker sees, or None when the card says it all."""
    moderator, guild = interaction.user, interaction.guild
    if not _approval_roles.staff & {role.name for role in moderator.roles}:
        return ":no_entry: Only admins, managers and moderators can decide on this request."

    ctf = ctfs.get(ctf_id)
    if ctf is None:
        return ":no_entry: This CTF no longer exists."

    member = await _member(guild, user_id)
    ctf_role = guild.get_role(ctf.role_id)
    if decision is not Decision.DECLINE:
        if member is None:
            return f"<@{user_id}> is no longer on the server, **Decline** to close this request."
        if ctf_role is None:
            return ":no_entry: The role of this CTF no longer exists."

    # Checked and settled before the next await, so a second click on the card is told it was already handled
    entry = ctfs.player(ctf.id, user_id)
    if entry is None or entry.status != "pending" or entry.approval_card_message_id != interaction.message.id:
        return "This request was already handled."

    if decision is Decision.DECLINE:
        ctfs.remove_player(ctf.id, user_id)
        problem = "left the server" if member is None else None if await _send_decline(member, ctf) else "DM failed"
    else:
        problem = await _accept(guild, member, ctf, ctf_role, entry, decision)

    line = decision_line(decision, moderator.id, problem)
    try:
        await interaction.edit_original_response(content=f"{interaction.message.content}\n{line}", view=None,
                                                 allowed_mentions=discord.AllowedMentions.none())
    except discord.HTTPException:
        # Decided all the same: tell the clicker, as later clicks on the card only say it was already handled
        logging.getLogger("bot").exception(f"Could not mark the decision on approval card {interaction.message.id}")
        return f"{line}, but the card could not be updated."
    return None


async def _accept(guild, member, ctf, ctf_role, entry, decision):
    """Let the member, waiting on the CTF's player list as entry, in with its role ctf_role, also as known player for
    Decision.ACCEPT_KNOWN. Returns what went wrong for the card, or None when nothing did."""
    roles, problem = [ctf_role], None
    if decision is Decision.ACCEPT_KNOWN:
        known = discord.utils.get(guild.roles, name=_approval_roles.known_player)
        if known is None:
            problem = "known-player role not found"
        else:
            roles.append(known)

    ctfs.add_player(ctf.id, member.id, datetime.now(timezone.utc))
    try:
        await member.add_roles(*roles)
    except BaseException:
        # Back to waiting on this card, so it can be tried again
        ctfs.reopen_request(ctf.id, member.id, entry.joined_at, entry.approval_card_message_id)
        raise
    await refresh_join_message(guild, ctf)
    return problem


async def _send_decline(member, ctf):
    """DM the member that they can't join the CTF for now; whether that worked."""
    try:
        await member.send(f"For now it was not possible to join **{discord.utils.escape_markdown(ctf.name)}**, "
                          f"go see a moderator on-site.")
    except discord.HTTPException:
        return False
    return True


async def _member(guild, user_id):
    """The member with this ID, or None when they are no longer on the server."""
    member = guild.get_member(user_id)
    if member is not None:
        return member
    try:
        return await guild.fetch_member(user_id)
    except discord.NotFound:
        return None
