"""The buttons the bot posts for a CTF: Join on its join message, Leave on its guide and the decisions on approval
cards. Their custom_id holds the CTF (and player), so the handlers in cogs/join_buttons.py keep working after a
restart."""

from enum import Enum

import discord

JOIN_TEMPLATE = r"ctf:join:(?P<ctf_id>[0-9]+)"
LEAVE_TEMPLATE = r"ctf:leave:(?P<ctf_id>[0-9]+)"
DECISION_TEMPLATE = r"ctf:card:(?P<decision>accept|known|decline):(?P<ctf_id>[0-9]+):(?P<user_id>[0-9]+)"


class Decision(Enum):
    # The value is part of the button's custom_id
    ACCEPT = "accept"
    ACCEPT_KNOWN = "known"
    DECLINE = "decline"


_DECISION_LOOKS = {
    Decision.ACCEPT: ("Accept", discord.ButtonStyle.success),
    Decision.ACCEPT_KNOWN: ("Accept + known player", discord.ButtonStyle.primary),
    Decision.DECLINE: ("Decline", discord.ButtonStyle.danger),
}


def join_button(ctf_id: int, disabled: bool = False) -> discord.ui.Button:
    return discord.ui.Button(
        label="Join", style=discord.ButtonStyle.success, custom_id=f"ctf:join:{ctf_id}", disabled=disabled
    )


def leave_button(ctf_id: int) -> discord.ui.Button:
    return discord.ui.Button(label="Leave", style=discord.ButtonStyle.secondary, custom_id=f"ctf:leave:{ctf_id}")


def decision_button(decision: Decision, ctf_id: int, user_id: int) -> discord.ui.Button:
    label, style = _DECISION_LOOKS[decision]
    return discord.ui.Button(label=label, style=style, custom_id=f"ctf:card:{decision.value}:{ctf_id}:{user_id}")


def join_view(ctf_id: int, disabled: bool = False) -> discord.ui.View:
    return discord.ui.View(timeout=None).add_item(join_button(ctf_id, disabled))


def leave_view(ctf_id: int) -> discord.ui.View:
    return discord.ui.View(timeout=None).add_item(leave_button(ctf_id))


def approval_view(ctf_id: int, user_id: int, offer_known_player: bool) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    for decision in Decision:
        if decision is not Decision.ACCEPT_KNOWN or offer_known_player:
            view.add_item(decision_button(decision, ctf_id, user_id))
    return view
