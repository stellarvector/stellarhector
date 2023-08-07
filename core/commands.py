import logging
import core.bot as bot

def load(load_commands):
    for handler in load_commands:
        __import__(f"command_handlers.{handler}")

    logging.getLogger("bot").debug(f"{len(load_commands)} commands loaded")

async def register():
    synced = await bot.client.tree.sync(guild=bot.guild)

    logging.getLogger("bot").debug(f"{len(synced)} commands registered and synced")
