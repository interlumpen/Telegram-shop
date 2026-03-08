from bot.logger_mesh import logger
from bot.misc.caching import CacheManager, cache_result
from typing import Dict, Any
import asyncio


class StatsCache:
    """Specialized cache for statistics"""

    def __init__(self, cache_manager: CacheManager):
        self.cache = cache_manager
        self.stats_ttl = 60  # 1 minute for statistics

    @cache_result(ttl=60, key_prefix="stats:daily")
    async def get_daily_stats(self, date: str) -> Dict[str, Any]:
        """Cached daily statistics"""
        from bot.database.methods import (
            select_today_users, select_today_orders,
            select_today_operations
        )

        return {
            "users": await select_today_users(date),
            "orders": await select_today_orders(date),
            "operations": await select_today_operations(date)
        }

    @cache_result(ttl=300, key_prefix="stats:global")
    async def get_global_stats(self) -> Dict[str, Any]:
        """Cached global statistics"""
        from bot.database.methods import (
            get_user_count, select_all_orders,
            select_count_items, select_count_goods
        )

        return {
            "total_users": await get_user_count(),
            "total_revenue": await select_all_orders(),
            "total_items": await select_count_items(),
            "total_goods": await select_count_goods()
        }

    async def warm_up_cache(self):
        """Warming up the cache at startup"""
        from datetime import date

        tasks = [
            self.get_daily_stats(date.today().isoformat()),
            self.get_global_stats()
        ]

        await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("Stats cache warmed up")