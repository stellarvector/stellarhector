"""The text of /ctf-status: one line per CTF the bot manages, with its stage, its next automatic step and its players."""
import discord

from utils import ctf_timeline, ctfs, text

# Discord refuses messages longer than this
MESSAGE_LIMIT = 2000

NONE_MANAGED = "No CTFs are managed by the bot right now."


def line(ctf, players, guild_id, now):
    """The CTF's line: its name linking to its main channel, its CTFtime event and dates (when it has them), its stage,
    its next automatic step at now ("manual" without CTFtime ID or dates) and how many of its players (ctfs.Player) joined and
    wait for a moderator."""
    # Brackets in the name would end the link text
    name = discord.utils.escape_markdown(ctf.name.replace("[", "(").replace("]", ")"))
    parts = [f"**[{name}](https://discord.com/channels/{guild_id}/{ctf.main_channel_id})**"]
    if ctf.ctftime_id is not None:
        parts.append(f"[CTFtime](<https://ctftime.org/event/{ctf.ctftime_id}/>)")
    if ctf.start is not None and ctf.finish is not None:
        parts.append(f"<t:{int(ctf.start.timestamp())}:f> – <t:{int(ctf.finish.timestamp())}:f>")
    parts += [ctf.stage.value, f"next: {_next(ctf, now)}", _players(players)]
    return " · ".join(parts)


def report(entries, guild_id, now, limit=MESSAGE_LIMIT):
    """The messages of /ctf-status for the entries (each a CTF and its players, in the order to list them): their lines,
    as few messages as fit in limit characters each, without splitting a line."""
    if not entries:
        return [NONE_MANAGED]

    messages = []
    for ctf, players in entries:
        new = text.cut(line(ctf, players, guild_id, now), limit)
        if messages and len(messages[-1]) + 1 + len(new) <= limit:
            messages[-1] += "\n" + new
        else:
            messages.append(new)
    return messages


def _next(ctf, now):
    if ctf_timeline.is_manual(ctf):
        return "manual"

    planned = ctf_timeline.next_step(ctf, now)
    if planned is None:
        return "nothing left"
    return f"{planned.step.value} <t:{int(planned.at.timestamp())}:R>"


def _players(players):
    joined = sum(player.status is ctfs.PlayerStatus.JOINED for player in players)
    return f"{joined} joined, {len(players) - joined} pending"
