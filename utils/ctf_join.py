"""Signing up for a CTF: the join message in #upcoming-ctfs with its Join button, and the Leave button on the guide in
the CTF's main channel.

decide and join_message are pure: who may join how, and what the join message says. The buttons keep working after a
restart: their custom_id holds the CTF's ID, and register makes the bot handle them for every CTF.
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


@dataclass(frozen=True)
class JoinRoles:
    """Names of the roles that let someone join: trusted ones (core and known players, staff) join right away, the
    player role (None when not configured) waits for a moderator."""
    trusted: frozenset[str]
    player: str | None


# The roles that let someone join, set by register
_roles = None
# Per CTF ID: two refreshes at once could edit its join message in the wrong order, the older list last
_refresh_locks = defaultdict(asyncio.Lock)

STILL_PENDING = "Still waiting for moderator confirmation"


def register(client, roles):
    """Handle the Join and Leave buttons of every CTF from now on, letting people join with the JoinRoles roles."""
    global _roles

    _roles = roles
    client.add_dynamic_items(JoinButton, LeaveButton)


def join_view(ctf_id):
    """The Join button of the CTF's join message."""
    return discord.ui.View(timeout=None).add_item(JoinButton(ctf_id))


def leave_view(ctf_id):
    """The Leave button of the guide in the CTF's main channel."""
    return discord.ui.View(timeout=None).add_item(LeaveButton(ctf_id))


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
        await _answer(interaction, _join(interaction, self.ctf_id))


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
        await _answer(interaction, _leave(interaction, self.ctf_id))


async def _answer(interaction, work):
    """Run work, a coroutine giving the reply, and send that reply only to the one who clicked."""
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        reply = await work
    except Exception:
        logging.getLogger("bot").exception(f"Handling a click on {interaction.data.get('custom_id')} failed")
        reply = "Sorry, an unknown error occurred, please ask a moderator for help."
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
        # TODO ctf-lifecycle 04: the full approval card, with the member's details and Accept/Decline buttons
        card = await bot_channel.send(
            f":raising_hand: {member.mention} wants to join **{discord.utils.escape_markdown(ctf.name)}**. "
            f"Let them in with `/add-player`.", allowed_mentions=discord.AllowedMentions.none())
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
