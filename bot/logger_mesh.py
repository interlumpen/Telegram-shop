import os
import logging
from logging.handlers import RotatingFileHandler

from bot.misc import EnvKeys

# Exported loggers (imported by other modules)
logger = logging.getLogger("bot")
audit_logger = logging.getLogger("bot.audit")


def configure_logging(console: bool = True, debug: bool = False):
    level = logging.DEBUG if debug else logging.INFO

    # Resetting handlers and setting the level
    for lg in (logger, audit_logger):
        lg.setLevel(level)
        lg.propagate = False
        if lg.handlers:
            lg.handlers.clear()

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    # stdout — default (for containers)
    if console:
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        logger.addHandler(sh)
        audit_logger.addHandler(sh)

    # file — only if explicitly enabled
    if EnvKeys.LOG_TO_FILE == "1":
        bot_path = EnvKeys.BOT_LOGFILE
        audit_path = EnvKeys.BOT_AUDITFILE

        for p in {bot_path, audit_path}:
            os.makedirs(os.path.dirname(p) or ".", exist_ok=True)

        bot_fh = RotatingFileHandler(bot_path, maxBytes=5_000_000, backupCount=3, encoding="utf-8")
        bot_fh.setFormatter(fmt)
        logger.addHandler(bot_fh)

        audit_fh = RotatingFileHandler(audit_path, maxBytes=5_000_000, backupCount=3, encoding="utf-8")
        audit_fh.setFormatter(fmt)
        audit_logger.addHandler(audit_fh)

    # Disable redundant logs from aiogram
    # Show only WARNINGS and above for these components
    for name in (
            "aiogram.client",
            "aiogram.methods",
            "aiogram.fsm",
            "aiogram.event",
            "aiogram.middlewares",
            "aiogram.dispatcher"
    ):
        logging.getLogger(name).setLevel(logging.WARNING)

    if not debug:
        logging.getLogger("aiogram.dispatcher").setLevel(logging.ERROR)

    return logger, audit_logger
