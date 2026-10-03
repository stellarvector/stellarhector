# Creates a channel per challenge category (web, crypto, pwn, ...) in the CTF's category
# Can be run from the CTF's main channel
#   by all players of this ctf (i.e. having the ctf role), administrators, managers and moderators
import core.bot as bot
import discord
from discord import app_commands
from error_handlers.default import default as default_error_handler
from utils import ctf_categories, ctf_places
from utils.ctf_places import Place


@bot.client.tree.command(name="add-category", description="Add challenge categories to the CTF", guild=bot.guild)
@app_commands.describe(names="The categories, comma-separated (web, crypto, pwn, ...)")
async def add_category(interaction: discord.Interaction, names: str):
    location = await ctf_places.locate_or_refuse(interaction, Place.MAIN)
    if location is None:
        return

    if not ctf_categories.may_add(interaction.user, location.ctf, bot.STAFF_ROLES):
        await interaction.response.send_message(
            ":no_entry: You are not playing this CTF so you can't add a category.\n"
            "If you are playing please ask a moderator.", ephemeral=True)
        return

    await interaction.response.defer(thinking=True)

    added = await ctf_categories.add_categories(interaction.guild, location.ctf, names)

    await interaction.edit_original_response(content=ctf_categories.report(added))

@add_category.error
async def error_on_add_category_command(interaction, error):
    await default_error_handler(interaction, error)
