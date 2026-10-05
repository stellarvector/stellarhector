"""A CTF's challenge categories (/add-category), a thread per challenge (/create-challenge), and marking challenges
solved (/solved, /unsolve). A locked CTF refuses them all."""

from typing import cast

import discord
from discord import app_commands
from discord.ext import commands

from bot import Hector
from cogs.replies import LOCKED, ctf_or_refuse, guild, member, refuse
from core import checks
from ctf import categories, challenges
from ctf.categories import Added
from ctf.challenges import Started
from ctf.location import Place, is_player_or_staff, locate

# A thread name holds up to 100 characters, and a solved one is renamed to `✅ <slug>`
MAX_CHALLENGE_NAME = 98

NOT_PLAYING = ":no_entry: You are not playing this CTF so you can't {}.\nIf you are playing please ask a moderator."
NOT_IN_CATEGORY = (
    "Run this in a category channel of the CTF, or in a challenge thread. "
    "Create a category channel with `/add-category` in the main channel if needed."
)
NOT_IN_CHALLENGE = "Run this in a challenge thread of the CTF, started with `/create-challenge`."


def _thread(interaction: discord.Interaction) -> discord.Thread:
    # Only called once the channel is known to be a challenge thread
    return cast(discord.Thread, interaction.channel)


def added_reply(added: Added) -> str:
    lines = []
    if added.created:
        lines.append(f"Created {', '.join(f'<#{channel.id}>' for channel in added.created)} :muscle:")
    if added.existing:
        lines.append(f"Already exists: {', '.join(f'<#{category.channel_id}>' for category in added.existing)}")
    if added.invalid:
        names = ", ".join(f"`{name}`" for name in added.invalid)
        lines.append(f"Skipped {names}: a category name needs letters or digits")
    return "\n".join(lines) or "Give the category names, comma-separated: `/add-category web, crypto, pwn`"


def started_reply(started: Started) -> str:
    if started.created:
        return f"Started {started.thread.mention}, go solve that thing :muscle:"
    return f"`{started.slug}` already exists, you were added to {started.thread.mention}"


class Challenges(commands.Cog):
    def __init__(self, bot: Hector) -> None:
        self.bot = bot

    @app_commands.command(name="add-category", description="Add challenge categories to the CTF")
    @app_commands.describe(names="The categories, comma-separated (web, crypto, pwn, ...)")
    async def add_category_command(self, interaction: discord.Interaction, names: str) -> None:
        ctf = await ctf_or_refuse(interaction, Place.MAIN)
        if ctf is None:
            return
        if ctf.locked_at is not None:
            await refuse(interaction, LOCKED)
            return
        if not is_player_or_staff(member(interaction), ctf, self.bot.settings.roles.staff):
            await interaction.response.send_message(NOT_PLAYING.format("add a category"), ephemeral=True)
            return

        await interaction.response.defer(thinking=True)
        added = await categories.add_categories(guild(interaction), ctf, names)
        await interaction.edit_original_response(content=added_reply(added))

    @app_commands.command(name="create-challenge", description="Start a challenge thread, or join it when it exists")
    @app_commands.describe(name="The challenge name")
    async def create_challenge_command(
        self, interaction: discord.Interaction, name: app_commands.Range[str, 1, MAX_CHALLENGE_NAME]
    ) -> None:
        """Run in a category channel, or in a challenge thread to use its parent channel."""
        location = locate(interaction.channel)
        category = challenges.category_of(location)
        if category is None or location.ctf is None or location.category_channel is None:
            await refuse(interaction, NOT_IN_CATEGORY)
            return
        if location.ctf.locked_at is not None:
            await refuse(interaction, LOCKED)
            return
        if not is_player_or_staff(member(interaction), location.ctf, self.bot.settings.roles.staff):
            await interaction.response.send_message(NOT_PLAYING.format("add a challenge"), ephemeral=True)
            return
        slug = categories.slug(name)
        if not slug:
            await refuse(interaction, "A challenge name needs letters or digits.")
            return

        await interaction.response.defer(thinking=True, ephemeral=True)
        started = await challenges.start_challenge(
            guild(interaction), location.ctf, category, location.category_channel, member(interaction), slug
        )
        await interaction.edit_original_response(content=started_reply(started))

    @app_commands.command(name="solved", description="Use in a challenge to indicate you have solved the challenge.")
    @app_commands.describe(flag="The correct flag for this challenge")
    async def solved_command(self, interaction: discord.Interaction, flag: str) -> None:
        """Only the CTF's players, not staff, can mark a challenge solved."""
        location = locate(interaction.channel)
        challenge = challenges.challenge_at(location, interaction.channel)
        if challenge is None or location.ctf is None:
            await refuse(interaction, NOT_IN_CHALLENGE)
            return
        if location.ctf.locked_at is not None:
            await refuse(interaction, LOCKED)
            return
        if member(interaction).get_role(location.ctf.role_id) is None:
            await interaction.response.send_message(NOT_PLAYING.format("mark a challenge solved"), ephemeral=True)
            return

        await interaction.response.defer(thinking=True)
        if not await challenges.mark_solved(guild(interaction), location.ctf, _thread(interaction), challenge, True):
            await interaction.edit_original_response(
                content="This challenge is already solved.\nIf this was a mistake please ask a moderator."
            )
            return

        await interaction.edit_original_response(
            content=f"Nice, great work! :partying_face:\nSolved by {interaction.user.mention} with `{flag}`."
        )

    @app_commands.command(name="unsolve", description="Use in a challenge to revert the solving of the challenge.")
    @checks.staff_only()
    async def unsolve_command(self, interaction: discord.Interaction) -> None:
        location = locate(interaction.channel)
        challenge = challenges.challenge_at(location, interaction.channel)
        if challenge is None or location.ctf is None:
            await refuse(interaction, NOT_IN_CHALLENGE)
            return
        if location.ctf.locked_at is not None:
            await refuse(interaction, LOCKED)
            return

        await interaction.response.defer(thinking=True)
        if not await challenges.mark_solved(guild(interaction), location.ctf, _thread(interaction), challenge, False):
            await interaction.edit_original_response(
                content="This challenge is not solved.\n"
                "In order to mark a challenge as unsolved it should have been marked as solved."
            )
            return

        await interaction.edit_original_response(content="Turns out this wasn't a solve after all :pensive:")
