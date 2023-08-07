import logging
import core.commands as commands
import core.bot as bot

async def handle():
    await commands.register()
    logging.getLogger("bot").info(f"Logged on as {bot.client.user}!")
