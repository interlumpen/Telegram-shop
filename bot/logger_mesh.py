import atexit
import os
import logging
import queue
from logging.handlers import RotatingFileHandler, QueueHandler, QueueListener

from bot.misc import EnvKeys

# Exported loggers (imported by other modules)
logger = logging.getLogger("bot")
audit_logger = logging.getLogger("bot.audit")

# Active QueueListeners feeding the file handlers; stopped on shutdown so queued records are flushed to disk.
_listeners: list[QueueListener] = []


def shutdown_logging() -> None:
    """Stop file-log listeners, flushing anything still queued."""
    while _listeners:
        listener = _listeners.pop()
        try:
            listener.stop()
        except Exception:
            pass


atexit.register(shutdown_logging)


def _queued_file_handler(path: str, fmt: logging.Formatter) -> QueueHandler:
    """A QueueHandler in front of a RotatingFileHandler.

    File writes are synchronous; behind the queue they run on the listener
    thread instead of blocking the event loop on every log record.
    """
    file_handler = RotatingFileHandler(path, maxBytes=5_000_000, backupCount=3, encoding="utf-8")
    file_handler.setFormatter(fmt)
    q = queue.SimpleQueue()
    listener = QueueListener(q, file_handler, respect_handler_level=True)
    listener.start()
    _listeners.append(listener)
    return QueueHandler(q)


def configure_logging(console: bool = True, debug: bool = False):
    level = logging.DEBUG if debug else logging.INFO

    # Reconfiguring: stop old listeners before dropping their handlers.
    shutdown_logging()

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

    # Root logger: catches plain logging.* calls and third-party loggers.
    # bot/bot.audit have propagate=False, so nothing prints twice.
    root = logging.getLogger()
    root.setLevel(level)
    if console and not any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        root_sh = logging.StreamHandler()
        root_sh.setFormatter(fmt)
        root.addHandler(root_sh)

    # file — only if explicitly enabled
    if EnvKeys.LOG_TO_FILE == "1":
        bot_path = EnvKeys.BOT_LOGFILE
        audit_path = EnvKeys.BOT_AUDITFILE

        for p in {bot_path, audit_path}:
            os.makedirs(os.path.dirname(p) or ".", exist_ok=True)

        logger.addHandler(_queued_file_handler(bot_path, fmt))
        audit_logger.addHandler(_queued_file_handler(audit_path, fmt))

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
    logging.getLogger("uvicorn").setLevel(logging.WARNING)

    if not debug:
        logging.getLogger("aiogram.dispatcher").setLevel(logging.ERROR)

    return logger, audit_logger
