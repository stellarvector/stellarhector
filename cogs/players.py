"""Who plays a CTF: the Join and Leave buttons, the decisions on approval cards, and /add-player and /remove-player.
The buttons work for every CTF, also after a restart: their custom_id says which CTF (see ctf/buttons.py)."""

import logging
import re
from collections.abc import Awaitable
from typing import Any, Self, cast

import discord
from discord import app_commands
from discord.ext import commands

from bot import Hector
from cogs.replies import ctf_or_refuse, guild, member
from core import checks
from core.settings import Settings
from ctf import buttons, joining
from ctf.approval import Decided, RequestRefusal, decide_request, decision_line
from ctf.buttons import Decision
from ctf.joining import JoinOutcome
from ctf.location import Place

log = logging.getLogger("bot")

STILL_PENDING = "Still waiting for moderator confirmation"
UNKNOWN_ERROR = "Sorry, an unknown error occurred, please ask a moderator for help."


class Players(commands.Cog):
    def __init__(self, bot: Hector) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(JoinButton, LeaveButton, DecisionButton)

    @app_commands.command(name="add-player", description="Add a new player to the ctf")
    @app_commands.describe(player="Player")
    @checks.staff_only()
    async def add_player_command(self, interaction: discord.Interaction, player: discord.Member) -> None:
        ctf = await ctf_or_refuse(interaction, Place.BOT)
        if ctf is None:
            return

        await interaction.response.defer(thinking=True)
        if not await joining.add_player(guild(interaction), player, ctf):
            await interaction.edit_original_response(content=f":no_entry: The role of `{ctf.name}` no longer exists.")
            return
        await interaction.edit_original_response(content=f"{player.mention} was added as player in `{ctf.name}`")

    @app_commands.command(name="remove-player", description="Remove a player from a ctf")
    @app_commands.describe(player="Player")
    @checks.staff_only()
    async def remove_player_command(self, interaction: discord.Interaction, player: discord.Member) -> None:
        ctf = await ctf_or_refuse(interaction, Place.BOT)
        if ctf is None:
            return

        await interaction.response.defer(thinking=True, ephemeral=True)
        await joining.remove_player(guild(interaction), player, ctf)
        await interaction.edit_original_response(content=f"{player.mention} was removed as player from `{ctf.name}`")


def _settings(interaction: discord.Interaction) -> Settings:
    return cast(Hector, interaction.client).settings


async def _answer(interaction: discord.Interaction, reply: Awaitable[str | None], thinking: bool) -> None:
    """Send the click's reply only to the one who clicked. While thinking, they see the bot is busy; otherwise the
    click is acknowledged as an update of the message."""
    if thinking:
        await interaction.response.defer(ephemeral=True, thinking=True)
    else:
        await interaction.response.defer()
    try:
        content = await reply
    except Exception:
        custom_id = cast(dict[str, object], interaction.data or {}).get("custom_id")
        log.exception(f"Handling a click on {custom_id} failed")
        content = UNKNOWN_ERROR
    if content is not None:
        await interaction.followup.send(content, ephemeral=True)


class JoinButton(discord.ui.DynamicItem[discord.ui.Button], template=buttons.JOIN_TEMPLATE):
    def __init__(self, ctf_id: int) -> None:
        super().__init__(buttons.join_button(ctf_id))
        self.ctf_id = ctf_id

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction, item: discord.ui.Item[Any], match: re.Match[str]
    ) -> Self:
        return cls(int(match["ctf_id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        await _answer(interaction, self._join(interaction), thinking=True)

    async def _join(self, interaction: discord.Interaction) -> str:
        result = await joining.join(guild(interaction), member(interaction), self.ctf_id, _settings(interaction).roles)
        if result.ctf is None:
            return ":no_entry: This CTF no longer exists."

        main = f"<#{result.ctf.main_channel_id}>"
        name = discord.utils.escape_markdown(result.ctf.name)
        return {
            JoinOutcome.JOINED: f"You're in, see {main}",
            JoinOutcome.ALREADY_JOINED: f"You're already playing, see {main}",
            JoinOutcome.PENDING: "Waiting for moderator confirmation",
            JoinOutcome.STILL_PENDING: STILL_PENDING,
            JoinOutcome.NO_PLAYER_ROLE: f"You can't join **{name}** this way, ask a moderator to add you.",
            JoinOutcome.CLOSED: f":no_entry: Joining **{name}** is closed.",
            JoinOutcome.ROLE_GONE: ":no_entry: The role of this CTF no longer exists, ask a moderator.",
            JoinOutcome.BOT_CHANNEL_GONE: ":no_entry: The #bot channel of this CTF no longer exists, ask a moderator.",
            JoinOutcome.CTF_GONE: ":no_entry: This CTF no longer exists.",
        }[result.outcome]


class LeaveButton(discord.ui.DynamicItem[discord.ui.Button], template=buttons.LEAVE_TEMPLATE):
    def __init__(self, ctf_id: int) -> None:
        super().__init__(buttons.leave_button(ctf_id))
        self.ctf_id = ctf_id

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction, item: discord.ui.Item[Any], match: re.Match[str]
    ) -> Self:
        return cls(int(match["ctf_id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        await _answer(interaction, self._leave(interaction), thinking=True)

    async def _leave(self, interaction: discord.Interaction) -> str:
        ctf = await joining.leave(guild(interaction), member(interaction), self.ctf_id)
        if ctf is None:
            return "You're not on the player list of this CTF, there is nothing to leave."
        return f"You left **{discord.utils.escape_markdown(ctf.name)}**"


class DecisionButton(discord.ui.DynamicItem[discord.ui.Button], template=buttons.DECISION_TEMPLATE):
    def __init__(self, decision: Decision, ctf_id: int, user_id: int) -> None:
        super().__init__(buttons.decision_button(decision, ctf_id, user_id))
        self.decision, self.ctf_id, self.user_id = decision, ctf_id, user_id

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction, item: discord.ui.Item[Any], match: re.Match[str]
    ) -> Self:
        return cls(Decision(match["decision"]), int(match["ctf_id"]), int(match["user_id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        # Not thinking: the click is acknowledged as an update of the card, which _decide edits
        await _answer(interaction, self._decide(interaction), thinking=False)

    async def _decide(self, interaction: discord.Interaction) -> str | None:
        """Returns the reply for the clicker, or None when the card says it all."""
        assert interaction.message is not None
        card = interaction.message
        outcome = await decide_request(
            guild(interaction),
            member(interaction),
            self.decision,
            self.ctf_id,
            self.user_id,
            card.id,
            _settings(interaction).roles,
        )
        if isinstance(outcome, RequestRefusal):
            return {
                RequestRefusal.NOT_STAFF: ":no_entry: Only admins, managers and moderators can decide on this request.",
                RequestRefusal.CTF_GONE: ":no_entry: This CTF no longer exists.",
                RequestRefusal.MEMBER_LEFT: f"<@{self.user_id}> is no longer on the server, **Decline** to close this "
                "request.",
                RequestRefusal.ROLE_GONE: ":no_entry: The role of this CTF no longer exists.",
                RequestRefusal.ALREADY_HANDLED: "This request was already handled.",
            }[outcome]
        return await self._mark_on_card(interaction, card, outcome)

    async def _mark_on_card(
        self, interaction: discord.Interaction, card: discord.Message, decided: Decided
    ) -> str | None:
        line = decision_line(self.decision, interaction.user.id, decided.problem)
        try:
            await interaction.edit_original_response(
                content=f"{card.content}\n{line}", view=None, allowed_mentions=discord.AllowedMentions.none()
            )
        except discord.HTTPException:
            # Decided all the same: later clicks on the card only say it was already handled
            log.exception(f"Could not mark the decision on approval card {card.id}")
            return f"{line}, but the card could not be updated."
        return None
