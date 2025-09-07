import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage

from bot.misc import EnvKeys
from bot.handlers import register_all_handlers
from bot.database.models import register_models
from bot.logger_mesh import configure_logging
from bot.middleware import setup_rate_limiting, RateLimitConfig
from bot.misc.storage import get_redis_storage


async def __on_start_up(dp: Dispatcher) -> None:
    register_all_handlers(dp)
    register_models()

    rate_config = RateLimitConfig(
        global_limit=30,
        global_window=60,
        ban_duration=300,
        admin_bypass=True
    )
    setup_rate_limiting(dp, rate_config)


async def start_bot() -> None:
    configure_logging(console=EnvKeys.LOG_TO_STDOUT == "1", debug=EnvKeys.DEBUG == "1")
    logging.basicConfig(level=logging.INFO)

    # Get appropriate storage
    storage = get_redis_storage() or MemoryStorage()
    if isinstance(storage, MemoryStorage):
        logging.warning("Using MemoryStorage - FSM states will be lost on restart!")

    dp = Dispatcher(storage=storage)
    await __on_start_up(dp)

    async with Bot(
            token=EnvKeys.TOKEN,
            default=DefaultBotProperties(
                parse_mode="HTML",
                link_preview_is_disabled=False,
                protect_content=False,
            ),
    ) as bot:
        # Close Redis connection on shutdown if using RedisStorage
        try:
            await dp.start_polling(
                bot,
                allowed_updates=["message", "callback_query", "pre_checkout_query"],
                handle_signals=False,
            )
        finally:
            if isinstance(storage, RedisStorage):
                await storage.close()
