"""The join message of a CTF in #upcoming-ctfs: who plays and when the on-campus sessions are. It is reposted at the
bottom of the channel for the last call."""

import asyncio
import logging
from collections import defaultdict
from dataclasses import replace
from datetime import UTC, datetime
from typing import cast

import discord

from ctf import store
from ctf.buttons import join_view
from ctf.models import Ctf, PlayerStatus
from feeds.calendar.sessions import Session, linked_sessions
from utils.text import cut, period

log = logging.getLogger("bot")

# Keeps the join message under Discord's 2000 characters
PLAYER_LIMIT = 20
SESSION_LIMIT = 5
SESSION_TITLE_LIMIT = 100

# Per CTF: two refreshes at once could leave the older player list on the message
_refresh_locks: defaultdict[int, asyncio.Lock] = defaultdict(asyncio.Lock)


class LastCallRefused(Exception):
    """Nothing changed; the message tells the user why."""


def join_message(ctf: Ctf, player_ids: list[int], sessions: list[Session]) -> str:
    name = discord.utils.escape_markdown(ctf.name)
    released = ctf.released_at is not None
    if released:
        lines = [f"## :unlock: {name}"]
    elif ctf.last_call_at is None:
        lines = [f"## :zap: {name}"]
    else:
        lines = [f"## :rotating_light: Last call: {name}"]
    if ctf.ctftime_id is not None:
        lines.append(f"<https://ctftime.org/event/{ctf.ctftime_id}/>")
    if ctf.start is not None and ctf.finish is not None:
        lines.append(f"From {period(ctf.start, ctf.finish)}")

    if released:
        lines.append(_playing(player_ids, released=True))
        lines.append(f"**Joining is closed:** the CTF is open to all members, see <#{ctf.main_channel_id}>")
        return "\n".join(lines)

    if sessions:
        lines.append("**On campus:**")
        for session in sorted(sessions, key=lambda session: session.start)[:SESSION_LIMIT]:
            title = discord.utils.escape_markdown(cut(session.title, SESSION_TITLE_LIMIT))
            lines.append(f"- {title}: {period(session.start, session.end)}")
        if len(sessions) > SESSION_LIMIT:
            lines.append(f"- and {len(sessions) - SESSION_LIMIT} more")

    lines.append(_playing(player_ids))
    return "\n".join(lines)


def _playing(player_ids: list[int], released: bool = False) -> str:
    if not player_ids:
        return "**Playing:** nobody" if released else "**Playing:** nobody yet, click **Join** to be the first"

    names = ", ".join(f"<@{user_id}>" for user_id in player_ids[:PLAYER_LIMIT])
    more = f" and {len(player_ids) - PLAYER_LIMIT} more" if len(player_ids) > PLAYER_LIMIT else ""
    return f"**Playing ({len(player_ids)}):** {names}{more}"


def current_join_message(ctf: Ctf, now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    return join_message(ctf, joined_ids(ctf.id), current_sessions(ctf, now))


def joined_ids(ctf_id: int) -> list[int]:
    """The players who joined (not those waiting for a moderator), in the order they joined."""
    return [player.user_id for player in store.players(ctf_id) if player.status is PlayerStatus.JOINED]


def current_sessions(ctf: Ctf, now: datetime) -> list[Session]:
    """The calendar sessions linking to the CTF's CTFtime event that haven't ended yet."""
    if ctf.ctftime_id is None:
        return []
    return [session for session in linked_sessions().get(ctf.ctftime_id, []) if session.end > now]


async def post_last_call(guild: discord.Guild, ctf: Ctf, channel_id: int | None, now: datetime) -> Ctf:
    """Repost the join message as a last call at the bottom of #upcoming-ctfs and delete the old one."""
    channel = None if channel_id is None else cast(discord.TextChannel | None, guild.get_channel(channel_id))
    if channel is None or channel_id is None:
        raise LastCallRefused("#upcoming-ctfs is not configured or no longer exists.")

    # Under the refresh lock, so no join or leave edits the old message in between
    async with _refresh_locks[ctf.id]:
        # Re-read: joining may have closed since `ctf` was read
        old = store.reread(ctf.id)
        if ctf.joining_closed or old.joining_closed:
            raise LastCallRefused(
                f"Joining **{discord.utils.escape_markdown(ctf.name)}** is closed, there is no last call to make."
            )

        message = await channel.send(
            current_join_message(replace(old, last_call_at=now), now),
            view=join_view(ctf.id),
            allowed_mentions=discord.AllowedMentions.none(),
        )
        try:
            store.mark_last_call(ctf.id, channel_id, message.id, now)
        except BaseException:
            # Unstored, no refresh would ever update it: the old join message stays the one
            await message.delete()
            raise
        await _delete_join_message(guild, old)
    return store.reread(ctf.id)


async def _delete_join_message(guild: discord.Guild, ctf: Ctf) -> None:
    if ctf.join_message_id is None or ctf.join_channel_id is None:
        return
    channel = cast(discord.TextChannel | None, guild.get_channel(ctf.join_channel_id))
    if channel is None:
        return
    try:
        await channel.get_partial_message(ctf.join_message_id).delete()
    except discord.NotFound:
        pass
    except discord.HTTPException:
        log.exception(f"Could not delete the old join message of CTF {ctf.name!r}, delete it by hand")


async def refresh_join_message(guild: discord.Guild, ctf: Ctf, view: discord.ui.View | None = None) -> None:
    """Show the current players and sessions on the join message, and replace its buttons with `view` when given. A
    failed edit is only logged: the stored player list is right, and the next refresh tries again."""
    async with _refresh_locks[ctf.id]:
        # Re-read: the last call may have moved the join message since `ctf` was read
        current = store.get(ctf.id)
        if current is None or current.join_message_id is None or current.join_channel_id is None:
            return

        channel = cast(discord.TextChannel | None, guild.get_channel(current.join_channel_id))
        if channel is None:
            log.warning(f"The join message channel of CTF {current.name!r} no longer exists")
            return

        message = channel.get_partial_message(current.join_message_id)
        content = current_join_message(current)
        try:
            if view is None:
                await message.edit(content=content, allowed_mentions=discord.AllowedMentions.none())
            else:
                await message.edit(content=content, allowed_mentions=discord.AllowedMentions.none(), view=view)
        except discord.HTTPException:
            log.exception(f"Could not update the join message of CTF {current.name!r}")
