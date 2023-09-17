# Removes a member from the role for this ctf
# Can be run from a ctf category channel
#   by an administrator or ctf operator
import core.bot as bot
import discord
from discord import app_commands
from error_handlers.permissions import check_role_error
from error_handlers.default import default as default_error_handler


@bot.client.tree.command(name="remove-player", description="Remove a player from a ctf", guild=bot.guild)
@app_commands.describe(player="Player")
@app_commands.checks.has_any_role(
    bot.config.get("ADMIN_ROLE"),
    bot.config.get("CTF_OPERATOR_ROLE")
)
async def add_player(interaction, player: discord.Member):
    await interaction.response.defer(thinking=True, ephemeral=True)

    role_name = interaction.channel.category.name
    ctf_role = discord.utils.get(interaction.guild.roles, name=role_name)

    if not ctf_role:
        await interaction.edit_original_response(content=f"Please execute this command in a CTF category.")
        return

    await player.remove_roles(ctf_role)
    await interaction.edit_original_response(content=f"{player.mention} was removed as player from `{role_name}`")

@add_player.error
async def add_player_error(interaction, error):
    if await check_role_error(interaction, error):
        return

    await default_error_handler(interaction, error)
