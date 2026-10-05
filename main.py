import logging
from logging.handlers import RotatingFileHandler

import cogs
from bot import Hector
from core import db, settings

LOG_FORMAT = "[%(asctime)s][%(levelname)-8s] %(message)-80s\t[%(pathname)s:%(funcName)s:%(lineno)d]"
LOG_FILE_SIZE = 5 * 1024 * 1024
LOG_FILE_COUNT = 10

log = logging.getLogger("bot")


def init_logging(log_file: str | None) -> None:
    log.setLevel(logging.DEBUG)
    if log_file is None:
        return

    handler = RotatingFileHandler(log_file, maxBytes=LOG_FILE_SIZE, backupCount=LOG_FILE_COUNT, encoding="utf-8")
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    handler.setLevel(logging.DEBUG)
    log.addHandler(handler)


def main() -> None:
    env = settings.read_env()
    init_logging(settings.Settings.log_file_in(env))
    log.info("BOT STARTING")

    try:
        config = settings.Settings.from_env(env)
        config.warn_switched_off()
        db.init(config.database_path)
        bot = Hector(config, cogs=cogs.ALL)
        log.info("Bot configured, starting to run now")
        bot.run(config.bot_token)
    except Exception:
        log.exception("UNCAUGHT CRITICAL EXCEPTION")
        raise


if __name__ == "__main__":
    main()
