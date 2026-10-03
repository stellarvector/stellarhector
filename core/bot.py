import logging

import discord
from discord.ext import commands
from dotenv import dotenv_values
from jinja2 import Environment, PackageLoader, select_autoescape
import core.config as config_helpers

config = dotenv_values(".env")
guild = discord.Object(id=config.get("GUILD_ID"))
TIMEZONE = config_helpers.timezone(config)

# Role groups for has_any_role, e.g. @app_commands.checks.has_any_role(*bot.MANAGER_ROLES)
STAFF_ROLES = config_helpers.role_names(config, "ADMIN_ROLE", "MANAGER_ROLE", "MODERATOR_ROLE")
MANAGER_ROLES = config_helpers.role_names(config, "ADMIN_ROLE", "MANAGER_ROLE")
ADMIN_ROLES = config_helpers.role_names(config, "ADMIN_ROLE")
# Who joins a CTF with its Join button right away, and who waits for a moderator
TRUSTED_PLAYER_ROLES = config_helpers.role_names(config, "CORE_PLAYER_ROLE", "KNOWN_PLAYER_ROLE") + STAFF_ROLES
PLAYER_ROLE = config_helpers.role_name(config, "PLAYER_ROLE")
# What Accept + known player on an approval card gives
KNOWN_PLAYER_ROLE = config_helpers.role_name(config, "KNOWN_PLAYER_ROLE")

# Server-wide channels; a feature whose channel is None is switched off
FEATURE_CHANNELS = [
    "ADMIN_CHANNEL_ID",
    "CTF_SELECTION_CHANNEL_ID",
    "UPCOMING_CTFS_CHANNEL_ID",
    "CALENDAR_CHANNEL_ID",
    "LEARNING_FORUM_ID",
]

def channel_id(key):
    return config_helpers.channel_id(config, key)

async def channel(discord_id):
    return client.get_channel(discord_id) or await client.fetch_channel(discord_id)

async def alert_admins(message):
    """Post message in ADMIN_CHANNEL_ID, or only log it when that channel is not configured."""
    admin_channel_id = channel_id("ADMIN_CHANNEL_ID")
    if admin_channel_id is None:
        logging.getLogger("bot").warning(f"ADMIN_CHANNEL_ID is not configured, alert not posted: {message}")
        return

    admin_channel = await channel(admin_channel_id)
    await admin_channel.send(message, allowed_mentions=discord.AllowedMentions.none())

async def alert_ctf(ctf, message):
    """Post message in the #bot channel of the CTF (a ctfs.Ctf), or for the admins (alert_admins) when ctf is None or
    its #bot no longer exists."""
    if ctf is not None:
        try:
            bot_channel = await channel(ctf.bot_channel_id)
        except discord.NotFound:
            logging.getLogger("bot").warning(f"The #bot channel of CTF {ctf.name!r} no longer exists, alerting the "
                                             f"admins")
        else:
            await bot_channel.send(message, allowed_mentions=discord.AllowedMentions.none())
            return
    await alert_admins(message)

jinja_env = Environment(
    loader=PackageLoader("utils", "templates"),
    autoescape=select_autoescape()
)
client = None

def init():
    global client,tree

    intents = discord.Intents.default()
    intents.message_content = True
    intents.members = True

    client = commands.Bot(command_prefix="sv-", intents=intents)

def run():
    client.run(config.get("BOT_TOKEN"))

if __name__ == "__main__":
    print("Usage:")
    print("  python3 main.py")
