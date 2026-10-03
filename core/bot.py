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
