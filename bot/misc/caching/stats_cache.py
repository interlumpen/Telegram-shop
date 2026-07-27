import asyncio
from decimal import Decimal
from typing import Dict, Any

from sqlalchemy import func, select

from bot.logger_mesh import logger
from bot.misc.caching import CacheManager, cache_result

class StatsCache:
    """Specialized cache for statistics"""

    def __init__(self, cache_manager: CacheManager):
        self.cache = cache_manager
        self.stats_ttl = 60  # 1 minute for statistics

    @cache_result(ttl=60, key_prefix="stats:daily")
    async def get_daily_stats(self, date: str) -> Dict[str, Any]:
        """Cached daily statistics"""
        from bot.database.main import Database
        from bot.database.methods.read import _day_window
        from bot.database.models.main import BoughtGoods, Operations, User

        start_of_day, end_of_day = _day_window(date)

        async with Database().session() as s:
            row = (await s.execute(
                select(
                    select(func.count())
                    .select_from(User)
                    .where(User.registration_date >= start_of_day,
                           User.registration_date < end_of_day)
                    .scalar_subquery().label("users"),

                    select(func.coalesce(func.sum(BoughtGoods.price), 0))
                    .where(BoughtGoods.bought_datetime >= start_of_day,
                           BoughtGoods.bought_datetime < end_of_day)
                    .scalar_subquery().label("orders"),

                    select(func.coalesce(func.sum(Operations.operation_value), 0))
                    .where(Operations.operation_time >= start_of_day,
                           Operations.operation_time < end_of_day)
                    .scalar_subquery().label("operations"),
                )
            )).one()

        return {
            "users": row.users or 0,
            "orders": Decimal(str(row.orders or 0)),
            "operations": Decimal(str(row.operations or 0)),
        }

    @cache_result(ttl=300, key_prefix="stats:global")
    async def get_global_stats(self) -> Dict[str, Any]:
        """Cached global statistics"""
        from bot.database.main import Database
        from bot.database.models.main import BoughtGoods, Goods, ItemValues, User

        async with Database().session() as s:
            row = (await s.execute(
                select(
                    select(func.count()).select_from(User)
                    .scalar_subquery().label("total_users"),

                    select(func.coalesce(func.sum(BoughtGoods.price), 0))
                    .scalar_subquery().label("total_revenue"),

                    select(func.count()).select_from(ItemValues)
                    .scalar_subquery().label("total_items"),

                    select(func.count()).select_from(Goods)
                    .scalar_subquery().label("total_goods"),
                )
            )).one()

        return {
            "total_users": row.total_users or 0,
            "total_revenue": Decimal(str(row.total_revenue or 0)),
            "total_items": row.total_items or 0,
            "total_goods": row.total_goods or 0,
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
