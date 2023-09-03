import discord
from discord.ext import commands
from dotenv import dotenv_values
from jinja2 import Environment, PackageLoader, select_autoescape

config = dotenv_values(".env")
guild = discord.Object(id=config.get("GUILD_ID"))
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
