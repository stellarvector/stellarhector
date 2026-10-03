import logging
import core.commands as commands
import core.bot as bot
import core.scheduler as scheduler

async def handle():
    scheduler.start()
    await commands.register()
    logging.getLogger("bot").info(f"Logged on as {bot.client.user}!")
