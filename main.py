import logging
from datetime import timedelta
from logging.handlers import RotatingFileHandler
import core.bot as bot
import core.commands as commands
import core.db as db
import core.events as events
import core.scheduler as scheduler


LOAD_EVENTS = [
    "on_ready",
]
LOAD_COMMANDS = [
    "help",
    "create_ctf",
    "create_challenge",
    "add_player",
    "remove_ctf",
    "remove_player",
    "solved",
    "unsolve",
    "archive_ctf",
    "archive_channel",
    "release_ctf"
]


def init_logging():
    log_formatter = logging.Formatter("[%(asctime)s][%(levelname)-8s] %(message)-80s\t[%(pathname)s:%(funcName)s:%(lineno)d]")
    log_file = bot.config.get("LOG_FILE")
    megabyte = 1024*1024

    log_handler = RotatingFileHandler(log_file, mode='a', maxBytes=5*megabyte, backupCount=10, encoding='utf-8', delay=False)
    log_handler.setFormatter(log_formatter)
    log_handler.setLevel(logging.DEBUG)

    bot_log = logging.getLogger("bot")
    bot_log.setLevel(logging.DEBUG)
    bot_log.addHandler(log_handler)

if __name__ == "__main__":
    init_logging()
    logger = logging.getLogger("bot")

    logger.info("BOT STARTING")

    try:
        db.init(bot.config.get("DATABASE_PATH") or db.DEFAULT_PATH)
        watchdog_minutes = bot.config.get("WATCHDOG_TIMEOUT_MINUTES")
        scheduler.init(timedelta(minutes=int(watchdog_minutes)) if watchdog_minutes else scheduler.DEFAULT_WATCHDOG_LIMIT)
        for key in bot.FEATURE_CHANNELS:
            if bot.channel_id(key) is None:
                logger.warning(f"{key} is not configured, the feature using it is switched off")
        bot.init()
        events.load(LOAD_EVENTS)
        events.register(LOAD_EVENTS)
        commands.load(LOAD_COMMANDS)

        logger.info("Bot configured, starting to run now")
        bot.run()
    except Exception as raised_exception:
        logger.exception(f"UNCAUGHT CRITICAL EXCEPTION")
        raise
