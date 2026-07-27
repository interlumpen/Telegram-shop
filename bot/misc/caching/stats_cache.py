import asyncio
from decimal import Decimal
from typing import Any, Dict

from sqlalchemy import func, select

from bot.logger_mesh import logger
from bot.misc.caching import CacheManager, cache_result


def _restore_decimals(data: Dict[str, Any], fields: tuple[str, ...]) -> Dict[str, Any]:
    """Re-hydrate money fields a Redis round-trip turned into strings"""
    return {
        key: (Decimal(str(value)) if key in fields else value)
        for key, value in data.items()
    }


class StatsCache:
    """Specialized cache for statistics"""

    def __init__(self, cache_manager: CacheManager):
        self.cache = cache_manager
        self.stats_ttl = 60  # 1 minute for statistics

    # --- daily (today-scoped; dropped by invalidate_stats_cache on every write) ---

    @cache_result(ttl=60, key_prefix="stats:daily")
    async def _daily_stats(self, date: str) -> Dict[str, Any]:
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

                    select(func.count())
                    .select_from(BoughtGoods)
                    .where(BoughtGoods.bought_datetime >= start_of_day,
                           BoughtGoods.bought_datetime < end_of_day)
                    .scalar_subquery().label("orders_count"),
                )
            )).one()

        return {
            "users": row.users or 0,
            "orders": Decimal(str(row.orders or 0)),
            "operations": Decimal(str(row.operations or 0)),
            "orders_count": row.orders_count or 0,
        }

    async def get_daily_stats(self, date: str) -> Dict[str, Any]:
        """Cached daily statistics."""
        return _restore_decimals(await self._daily_stats(date), ("orders", "operations"))

    # --- global (all-time; TTL only, never dropped on the write path) ---

    @cache_result(ttl=300, key_prefix="stats:global")
    async def _global_stats(self) -> Dict[str, Any]:
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

    async def get_global_stats(self) -> Dict[str, Any]:
        """Cached global statistics."""
        return _restore_decimals(await self._global_stats(), ("total_revenue",))

    # --- dashboard (the rest of the admin statistics screen) ---

    @cache_result(ttl=60, key_prefix="stats:dashboard")
    async def _dashboard_stats(self) -> Dict[str, Any]:
        from bot.database.main import Database
        from bot.database.models.main import BoughtGoods, Categories, Operations, User

        async with Database().session() as s:
            row = (await s.execute(
                select(
                    select(func.count(func.distinct(BoughtGoods.buyer_id)))
                    .scalar_subquery().label("unique_buyers"),

                    select(func.coalesce(func.avg(BoughtGoods.price), 0))
                    .scalar_subquery().label("avg_order"),

                    select(func.count()).select_from(BoughtGoods)
                    .scalar_subquery().label("sold_count"),

                    select(func.count()).select_from(User)
                    .where(User.is_blocked.is_(True))
                    .scalar_subquery().label("blocked_users"),

                    select(func.coalesce(func.sum(User.balance), 0))
                    .scalar_subquery().label("users_balance"),

                    select(func.coalesce(func.sum(Operations.operation_value), 0))
                    .scalar_subquery().label("all_operations"),

                    select(func.count()).select_from(Categories)
                    .scalar_subquery().label("categories"),
                )
            )).one()

        return {
            "unique_buyers": row.unique_buyers or 0,
            "avg_order": Decimal(str(row.avg_order or 0)),
            "sold_count": row.sold_count or 0,
            "blocked_users": row.blocked_users or 0,
            "users_balance": Decimal(str(row.users_balance or 0)),
            "all_operations": Decimal(str(row.all_operations or 0)),
            "categories": row.categories or 0,
        }

    async def get_dashboard_stats(self) -> Dict[str, Any]:
        """The rest of the admin statistics screen, in one query"""
        return _restore_decimals(
            await self._dashboard_stats(),
            ("avg_order", "users_balance", "all_operations"),
        )

    async def warm_up_cache(self):
        """Warming up the cache at startup"""
        from datetime import date

        tasks = [
            self.get_daily_stats(date.today().isoformat()),
            self.get_global_stats(),
            self.get_dashboard_stats(),
        ]

        await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("Stats cache warmed up")
