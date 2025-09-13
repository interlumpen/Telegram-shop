import asyncio
from datetime import datetime
from bot.misc.cache import get_cache_manager
from bot.logger_mesh import logger


async def invalidate_stats_periodically():
    """Invalidate statistics every hour"""
    while True:
        await asyncio.sleep(3600)  # 1 hour

        cache = get_cache_manager()
        if cache:
            await cache.invalidate_pattern("stats:*")
            await cache.invalidate_pattern("user_count")
            await cache.invalidate_pattern("admin_count")
            logger.info("Stats cache invalidated by scheduler")


async def daily_cleanup():
    """Daily cleaning of outdated data"""
    while True:
        # Wait until 3 o'clock in the morning
        now = datetime.now()
        next_run = now.replace(hour=3, minute=0, second=0, microsecond=0)
        if now >= next_run:
            next_run = next_run.replace(day=next_run.day + 1)

        wait_seconds = (next_run - now).total_seconds()
        await asyncio.sleep(wait_seconds)

        cache = get_cache_manager()
        if cache:
            # Full invalidation of non-critical data
            await cache.invalidate_pattern("item:*")
            await cache.invalidate_pattern("category:*")
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
