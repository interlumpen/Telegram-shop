import asyncio
from datetime import datetime, timedelta, timezone
from bot.misc.caching import get_cache_manager
from bot.logger_mesh import logger


async def invalidate_stats_periodically():
    """Hourly janitor sweep for the stats caches.

    The write path (invalidate_stats_cache) does targeted deletes; this sweep
    only mops up stale dated keys (stats:daily:<old date>) once an hour.
    """
    while True:
        await asyncio.sleep(3600)  # 1 hour

        cache = get_cache_manager()
        if cache:
            await cache.invalidate_pattern("stats:*")
            await cache.delete("user_count:")
            await cache.delete("admin_count:")
            logger.info("Stats cache invalidated by scheduler")


_CATALOG_PREFIXES = (
    "item_info:", "item_values:", "item_infinite:", "avg_rating:",
    "category:", "category_items:",
)


async def daily_cleanup():
    """Daily cleaning of outdated data"""
    while True:
        # Wait until 3 o'clock in the morning (UTC)
        now = datetime.now(timezone.utc)
        next_run = now.replace(hour=3, minute=0, second=0, microsecond=0)
        if now >= next_run:
            next_run = next_run + timedelta(days=1)

        wait_seconds = (next_run - now).total_seconds()
        await asyncio.sleep(wait_seconds)

        cache = get_cache_manager()
        if cache:
            # Backstop for the targeted invalidation on the write path.
            for prefix in _CATALOG_PREFIXES:
                await cache.invalidate_pattern(f"{prefix}*")
            logger.info("Daily cache cleanup completed")


class CacheScheduler:
    """Scheduler for automatic cache invalidation"""

    def __init__(self):
        self.tasks = []

    async def start(self):
        """Starting the scheduler"""
        # Invalidate statistics every hour
        self.tasks.append(
            asyncio.create_task(invalidate_stats_periodically())
        )

        # Invalidation of outdated data once a day
        self.tasks.append(
            asyncio.create_task(daily_cleanup())
        )

        logger.info("Cache scheduler started")

    async def stop(self):
        """Stop the planner"""
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        logger.info("Cache scheduler stopped")
