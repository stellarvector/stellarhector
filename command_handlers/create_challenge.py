# Creates a challenge channel
# Can be run from a ctf category channel
#   by all players of this ctf (i.e. having the ctf role)
import core.bot as bot
import discord
from discord import app_commands
from utils.ctf import get_new_channel_position
from error_handlers.permissions import check_role_error
from error_handlers.default import default as default_error_handler


@bot.client.tree.command(name="create-challenge", description="Create a new CTF", guild=bot.guild)
@app_commands.describe(name="The challenge name")
@app_commands.describe(category="The category (web,crypto,pwn,rev,...)")
async def create_challenge(interaction: discord.Interaction, name: str, category: str):
    await interaction.response.defer()
    message_id = interaction.channel.last_message_id

    ctf_category = interaction.channel.category
    ctf_role = discord.utils.get(interaction.guild.roles, name=ctf_category.name)

    if not ctf_role or interaction.user.get_role(ctf_role.id) is None:
        await interaction.followup.edit_message(message_id, content="You are not playing this CTF so you can't add a challenge.\nIf you are playing please ask an admin.", ephemeral=True)
        return

    channel = await create_challenge_channel(interaction, f"{category}-{name}", ctf_category)

    await interaction.followup.edit_message(message_id,
        content=f"Done; {channel.mention} created!\nGo solve that thing :muscle:")

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
