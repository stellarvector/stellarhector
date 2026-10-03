# Creates a challenge channel
# Can be run from a CTF's main channel, one of its challenge channels or a thread in one
#   by all players of this ctf (i.e. having the ctf role)
import core.bot as bot
import discord
from discord import app_commands
from utils.ctf import get_new_channel_position
from error_handlers.permissions import check_role_error
from error_handlers.default import default as default_error_handler
from utils import ctf_places
from utils.ctf_places import Place


@bot.client.tree.command(name="create-challenge", description="Create a new CTF", guild=bot.guild)
@app_commands.describe(name="The challenge name")
@app_commands.describe(category="The category (web,crypto,pwn,rev,...)")
async def create_challenge(interaction: discord.Interaction, name: str, category: str):
    # TODO ctf-lifecycle 07: only in a category channel or a challenge thread, once challenges are threads
    location = await ctf_places.locate_or_refuse(interaction, Place.MAIN, Place.CATEGORY, Place.CHALLENGE)
    if location is None:
        return

    await interaction.response.defer(thinking=True, ephemeral=True)

    ctf_category = interaction.guild.get_channel(location.ctf.category_id)

    if interaction.user.get_role(location.ctf.role_id) is None:
        await interaction.edit_original_response(content="You are not playing this CTF so you can't add a challenge.\nIf you are playing please ask an admin.")
        return

    channel = await create_challenge_channel(interaction, f"{category}-{name}", ctf_category)

    await interaction.edit_original_response(content=f"Done; {channel.mention} created!\nGo solve that thing :muscle:")

async def create_challenge_channel(interaction, name, ctf_category):
    new_position = get_new_channel_position(ctf_category,name)
    challenge_channel = await interaction.guild.create_text_channel(name, category=ctf_category)
    await challenge_channel.edit(sync_permissions=True, position=new_position)

    return challenge_channel

@create_challenge.error
async def error_on_create_challenge_command(interaction, error):
    if await check_role_error(interaction, error):
        return

    await default_error_handler(interaction, error)
