# Starts a challenge: a thread in a category channel, with the user added to it
# Can be run from a CTF's category channel or a challenge thread (then its parent channel is used)
#   by all players of this ctf (i.e. having the ctf role), administrators, managers and moderators
import core.bot as bot
import discord
from discord import app_commands
from error_handlers.default import default as default_error_handler
from utils import ctf_categories, ctf_challenges, ctf_places

# A thread name holds up to 100 characters, and a solved one is renamed to `✅ <slug>`
_MAX_NAME = 98


@bot.client.tree.command(name="create-challenge", description="Start a challenge thread, or join it when it exists",
                         guild=bot.guild)
@app_commands.describe(name="The challenge name")
async def create_challenge(interaction: discord.Interaction, name: app_commands.Range[str, 1, _MAX_NAME]):
    location = ctf_places.locate(interaction.channel)
    category = ctf_challenges.category_of(location)
    if category is None:
        await interaction.response.send_message(f":no_entry: {ctf_challenges.NOT_IN_CATEGORY}", ephemeral=True)
        return

    if not ctf_categories.may_add(interaction.user, location.ctf, bot.STAFF_ROLES):
        await interaction.response.send_message(
            ":no_entry: You are not playing this CTF so you can't add a challenge.\n"
            "If you are playing please ask a moderator.", ephemeral=True)
        return

    slug = ctf_categories.slug(name)
    if not slug:
        await interaction.response.send_message(":no_entry: A challenge name needs letters or digits.", ephemeral=True)
        return

    await interaction.response.defer(thinking=True, ephemeral=True)

    started = await ctf_challenges.start(interaction.guild, location.ctf, category, location.category_channel,
                                         interaction.user, slug)

    await interaction.edit_original_response(content=ctf_challenges.reply(started))

@create_challenge.error
async def error_on_create_challenge_command(interaction, error):
    await default_error_handler(interaction, error)
