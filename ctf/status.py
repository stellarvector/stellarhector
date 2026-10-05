"""The text of /ctf-status: one line per CTF the bot manages, with its stage, its next automatic step and its
players."""

from collections.abc import Sequence
from datetime import datetime

import discord

from ctf import timeline
from ctf.models import Ctf, Player, PlayerStatus
from utils import text

# Discord refuses messages longer than this
MESSAGE_LIMIT = 2000

NONE_MANAGED = "No CTFs are managed by the bot right now."


def line(ctf: Ctf, players: Sequence[Player], guild_id: int, now: datetime) -> str:
    """Returns the CTF's name linking to its main channel, its CTFtime event and dates when it has them, its stage, its
    next automatic step ("manual" without a CTFtime ID or dates), and how many players have joined or are pending."""
    # Brackets in the name would end the link text
    name = discord.utils.escape_markdown(ctf.name.replace("[", "(").replace("]", ")"))
    parts = [f"**[{name}](https://discord.com/channels/{guild_id}/{ctf.main_channel_id})**"]
    if ctf.ctftime_id is not None:
        parts.append(f"[CTFtime](<https://ctftime.org/event/{ctf.ctftime_id}/>)")
    if ctf.start is not None and ctf.finish is not None:
        parts.append(f"<t:{int(ctf.start.timestamp())}:f> – <t:{int(ctf.finish.timestamp())}:f>")
    parts += [ctf.stage.value, f"next: {_next(ctf, now)}", _players(players)]
    return " · ".join(parts)


def report(
    entries: Sequence[tuple[Ctf, Sequence[Player]]], guild_id: int, now: datetime, limit: int = MESSAGE_LIMIT
) -> list[str]:
    """Packs the lines of the `entries` into as few messages of at most `limit` characters as possible, without
    splitting a line."""
    if not entries:
        return [NONE_MANAGED]

    messages: list[str] = []
    for ctf, players in entries:
        new = text.cut(line(ctf, players, guild_id, now), limit)
        if messages and len(messages[-1]) + 1 + len(new) <= limit:
            messages[-1] += "\n" + new
        else:
            messages.append(new)
    return messages


def _next(ctf: Ctf, now: datetime) -> str:
    if timeline.is_manual(ctf):
        return "manual"

    planned = timeline.next_step(ctf, now)
    if planned is None:
        return "nothing left"
    return f"{planned.step.value} <t:{int(planned.at.timestamp())}:R>"


def _players(players: Sequence[Player]) -> str:
    joined = sum(player.status is PlayerStatus.JOINED for player in players)
    return f"{joined} joined, {len(players) - joined} pending"
