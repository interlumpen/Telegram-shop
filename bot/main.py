import logging
import sys
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage

from bot.database.methods import check_category_cached
from bot.handlers.admin.shop_management_states import init_stats_cache
from bot.misc import EnvKeys
from bot.handlers import register_all_handlers
from bot.database.models import register_models
from bot.logger_mesh import configure_logging
from bot.middleware import setup_rate_limiting, RateLimitConfig
from bot.middleware.security import SecurityMiddleware, AuthenticationMiddleware
from bot.misc.cache import init_cache_manager, get_cache_manager
from bot.misc.cache_scheduler import CacheScheduler
from bot.misc.storage import get_redis_storage


async def __on_start_up(dp: Dispatcher) -> None:
    """Initialize bot on startup"""

    # Registration of handlers and models
    register_all_handlers(dp)
    register_models()

    # Setting Rate Limiting
    rate_config = RateLimitConfig(
        global_limit=30,
        global_window=60,
        ban_duration=300,
        admin_bypass=True,
        action_limits={
            'broadcast': (1, 3600),  # 1 time per hour
            'payment': (10, 60),  # 10 times per minute
            'shop_view': (60, 60),  # 60 times per minute
            'admin_action': (30, 60),  # 30 times per minute
            'buy_item': (5, 60),  # 5 purchases per minute
            'top_up': (5, 300),  # 5 top-ups in 5 minutes
        }
    )
    setup_rate_limiting(dp, rate_config)

    # Add security middleware
    security_middleware = SecurityMiddleware()
    auth_middleware = AuthenticationMiddleware()

    # First authentication, then security, then rate limiting
    dp.message.middleware(auth_middleware)
    dp.callback_query.middleware(auth_middleware)

    dp.message.middleware(security_middleware)
    dp.callback_query.middleware(security_middleware)

    logging.info("Security middleware initialized")

    storage = get_redis_storage()
    if isinstance(storage, RedisStorage):
        # Use the same Redis for caching
        await init_cache_manager(storage.redis)

        # Initialize the statistics cache
        init_stats_cache()

        # Warm up critical caches at startup
        await warm_up_critical_caches()

        logging.info("Cache system initialized and warmed up")
    else:
        logging.warning("Redis not available - caching disabled")


async def warm_up_critical_caches():
    """Warming of critical caches at startup"""
    from bot.database.methods.read import (
        get_user_count_cached,
        select_admins_cached
    )

    cache_manager = get_cache_manager()
    if not cache_manager:
        return

    try:
        # Warming up the base stats
        await get_user_count_cached()
        await select_admins_cached()

        # Warming up popular categories and products
        from bot.database.methods import query_categories
        categories = await query_categories(limit=5)
        for category in categories:
            await check_category_cached(category)

        logging.info("Critical caches warmed up successfully")
    except Exception as e:
        logging.error(f"Failed to warm up caches: {e}")



async def start_bot() -> None:
    """Start the bot with enhanced security"""

    # Logging Configuration
    configure_logging(
        console=EnvKeys.LOG_TO_STDOUT == "1",
        debug=EnvKeys.DEBUG == "1"
    )

    # Logging level setting
    log_level = logging.DEBUG if EnvKeys.DEBUG == "1" else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Disconnect unnecessary logs from aiogram
    logging.getLogger("aiogram.dispatcher").setLevel(logging.WARNING)
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)
    logging.getLogger("aiogram.middlewares").setLevel(logging.WARNING)

    # Checking critical environment variables
    if not EnvKeys.TOKEN:
        logging.critical("Bot token not set! Please set TOKEN environment variable.")
        sys.exit(1)

    if not EnvKeys.OWNER_ID:
        logging.critical("Owner ID not set! Please set OWNER_ID environment variable.")
        sys.exit(1)

    # Retrieve storage (Redis or Memory)
    storage = get_redis_storage() or MemoryStorage()
    if isinstance(storage, MemoryStorage):
        logging.warning(
            "Using MemoryStorage - FSM states will be lost on restart! "
            "Consider setting up Redis for production."
        )

    cache_scheduler = CacheScheduler()
    await cache_scheduler.start()

    # Creating a dispatcher
    dp = Dispatcher(storage=storage)

    # Initialization at startup
    await __on_start_up(dp)

    # Create and run the bot
    async with Bot(
            token=EnvKeys.TOKEN,
            default=DefaultBotProperties(
                parse_mode="HTML",
                link_preview_is_disabled=False,
                protect_content=False,
            ),
    ) as bot:
        # Getting information about the bot
        bot_info = await bot.get_me()
        logging.info(f"Starting bot: @{bot_info.username} (ID: {bot_info.id})")

        try:
            # Start polling with signal processing
            await dp.start_polling(
                bot,
                allowed_updates=[
                    "message",
                    "callback_query",
                    "pre_checkout_query",
                    "successful_payment"
                ],
                handle_signals=True,
            )
        except Exception as e:
            logging.error(f"Bot polling error: {e}")
            raise
        finally:
            # Correctly closing connections
            if isinstance(storage, RedisStorage):
                await storage.close()
                logging.info("Redis connection closed")

            await bot.session.close()
            logging.info("Bot session closed")
