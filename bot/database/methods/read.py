import datetime
from decimal import Decimal
from functools import wraps
from typing import Optional, Dict, TypeVar, Callable, Any, Coroutine

from sqlalchemy import func, exists, select

from bot.database.models import Database, User, ItemValues, Goods, Categories, Role, BoughtGoods, \
    Operations, ReferralEarnings
from bot.misc.caching import get_cache_manager

F = TypeVar('F', bound=Callable[..., Coroutine[Any, Any, Any]])


def async_cached(ttl: int = 300, key_prefix: str = "") -> Callable[[F], F]:
    """Decorator for async functions with caching."""
    def decorator(async_func: F) -> F:
        @wraps(async_func)
        async def async_wrapper(*args, **kwargs):
            cache_key = f"{key_prefix or async_func.__name__}:{':'.join(str(arg) for arg in args)}"

            cache = get_cache_manager()
            if cache:
                cached_value = await cache.get(cache_key)
                if cached_value is not None:
                    return cached_value

            result = await async_func(*args, **kwargs)

            if cache and result is not None:
                await cache.set(cache_key, result, ttl)

            return result

        return async_wrapper

    return decorator


def _day_window(date_str: str) -> tuple[datetime.datetime, datetime.datetime]:
    d = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
    start = datetime.datetime.combine(d, datetime.time.min)
    end = start + datetime.timedelta(days=1)
    return start, end


def _obj_to_dict(obj, model) -> dict:
    """Convert an ORM object to a dict of column values."""
    return {c.key: getattr(obj, c.key) for c in model.__table__.columns}


# --- Async implementations ---

async def check_user(telegram_id: int | str) -> Optional[dict]:
    """Return user by Telegram ID or None if not found."""
    async with Database().session() as s:
        result = await s.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalars().one_or_none()
        return _obj_to_dict(user, User) if user else None


async def check_role(telegram_id: int) -> int:
    """Return permission bitmask for user (0 if none)."""
    async with Database().session() as s:
        result = await s.execute(
            select(Role.permissions).join(User, User.role_id == Role.id).where(User.telegram_id == telegram_id)
        )
        return result.scalar() or 0


async def get_role_id_by_name(role_name: str) -> Optional[int]:
    """Return role id by name or None."""
    async with Database().session() as s:
        return (await s.execute(select(Role.id).where(Role.name == role_name))).scalar()


async def check_role_name_by_id(role_id: int) -> str:
    """Return role name by id (raises if not found)."""
    async with Database().session() as s:
        result = await s.execute(select(Role.name).where(Role.id == role_id))
        return result.scalar_one()


async def select_max_role_id() -> Optional[int]:
    """Return role_id with the highest numeric permissions value (OWNER=127)."""
    async with Database().session() as s:
        result = await s.execute(select(Role.id).order_by(Role.permissions.desc()).limit(1))
        row = result.first()
        return row[0] if row else None


async def get_all_roles() -> list[dict]:
    """Return all roles as list of dicts ordered by permissions asc."""
    async with Database().session() as s:
        result = await s.execute(select(Role).order_by(Role.permissions.asc()))
        roles = result.scalars().all()
        return [{'id': r.id, 'name': r.name, 'permissions': r.permissions, 'default': r.default} for r in roles]


async def get_role_by_id(role_id: int) -> dict | None:
    """Return single role as dict or None."""
    async with Database().session() as s:
        result = await s.execute(select(Role).where(Role.id == role_id))
        r = result.scalars().first()
        return {'id': r.id, 'name': r.name, 'permissions': r.permissions, 'default': r.default} if r else None


async def get_roles_with_max_perms(max_perms: int) -> list[dict]:
    """Return roles whose permissions are a subset of max_perms (bitwise)."""
    async with Database().session() as s:
        result = await s.execute(select(Role).order_by(Role.permissions.asc()))
        roles = result.scalars().all()
        return [
            {'id': r.id, 'name': r.name, 'permissions': r.permissions, 'default': r.default}
            for r in roles
            if (r.permissions & ~max_perms) == 0
        ]


async def count_users_with_role(role_id: int) -> int:
    """Return count of users assigned to a given role."""
    async with Database().session() as s:
        return (await s.execute(
            select(func.count(User.telegram_id)).where(User.role_id == role_id)
        )).scalar() or 0


async def select_today_users(date: str) -> int:
    """Return count of users registered on given date (YYYY-MM-DD)."""
    start_of_day, end_of_day = _day_window(date)
    async with Database().session() as s:
        return (await s.execute(
            select(func.count()).select_from(User).where(
                User.registration_date >= start_of_day,
                User.registration_date < end_of_day
            )
        )).scalar() or 0


async def get_user_count() -> int:
    """Return total users count."""
    async with Database().session() as s:
        return (await s.execute(select(func.count()).select_from(User))).scalar() or 0


async def select_admins() -> int:
    """Return count of users with role_id > 1."""
    async with Database().session() as s:
        return (await s.execute(
            select(func.count(User.telegram_id)).where(User.role_id > 1)
        )).scalar() or 0


async def get_all_users() -> list[tuple[int]]:
    """Return list of all user telegram_ids (as tuples)."""
    async with Database().session() as s:
        result = await s.execute(select(User.telegram_id))
        return result.all()


async def get_bought_item_info(item_id: str) -> dict | None:
    """Return bought item row as dict by row id, or None."""
    async with Database().session() as s:
        result = await s.execute(select(BoughtGoods).where(BoughtGoods.id == item_id))
        obj = result.scalars().first()
        return _obj_to_dict(obj, BoughtGoods) if obj else None


async def get_item_info(item_name: str) -> dict | None:
    """Return item (position) row as dict by name, or None."""
    async with Database().session() as s:
        result = await s.execute(select(Goods).where(Goods.name == item_name))
        obj = result.scalars().first()
        return _obj_to_dict(obj, Goods) if obj else None


async def get_goods_info(item_id: int) -> dict | None:
    """Return item_value row as dict by id, including item_name from Goods."""
    async with Database().session() as s:
        result = await s.execute(
            select(ItemValues, Goods.name.label('item_name'))
            .join(Goods, Goods.id == ItemValues.item_id)
            .where(ItemValues.id == int(item_id))
        )
        row = result.first()
        if not row:
            return None
        d = _obj_to_dict(row.ItemValues, ItemValues)
        d['item_name'] = row.item_name
        return d


async def check_category(category_name: str) -> dict | None:
    """Return category as dict by name, or None."""
    async with Database().session() as s:
        result = await s.execute(select(Categories).where(Categories.name == category_name))
        obj = result.scalars().first()
        return _obj_to_dict(obj, Categories) if obj else None


async def select_item_values_amount(item_name: str) -> int:
    """Return count of item_values for an item (by item name)."""
    async with Database().session() as s:
        return (await s.execute(
            select(func.count(ItemValues.id))
            .join(Goods, Goods.id == ItemValues.item_id)
            .where(Goods.name == item_name)
        )).scalar() or 0


async def check_value(item_name: str) -> bool:
    """Return True if item has any infinite value (is_infinity=True)."""
    async with Database().session() as s:
        return (await s.execute(
            select(exists().where(
                ItemValues.item_id == Goods.id,
                Goods.name == item_name,
                ItemValues.is_infinity.is_(True),
            ))
        )).scalar()


async def select_user_items(buyer_id: int | str) -> int:
    """Return count of bought items for user."""
    async with Database().session() as s:
        return (await s.execute(
            select(func.count()).select_from(BoughtGoods).where(BoughtGoods.buyer_id == buyer_id)
        )).scalar() or 0


async def select_bought_item(unique_id: int) -> dict | None:
    """Return one bought item by unique_id as dict, or None."""
    async with Database().session() as s:
        result = await s.execute(select(BoughtGoods).where(BoughtGoods.unique_id == unique_id))
        obj = result.scalars().first()
        return _obj_to_dict(obj, BoughtGoods) if obj else None


async def select_count_items() -> int:
    """Return total count of item_values."""
    async with Database().session() as s:
        return (await s.execute(select(func.count()).select_from(ItemValues))).scalar() or 0


async def select_count_goods() -> int:
    """Return total count of goods (positions)."""
    async with Database().session() as s:
        return (await s.execute(select(func.count()).select_from(Goods))).scalar() or 0


async def select_count_categories() -> int:
    """Return total count of categories."""
    async with Database().session() as s:
        return (await s.execute(select(func.count()).select_from(Categories))).scalar() or 0


async def select_count_bought_items() -> int:
    """Return total count of bought items."""
    async with Database().session() as s:
        return (await s.execute(select(func.count()).select_from(BoughtGoods))).scalar() or 0


async def select_today_orders(date: str) -> Decimal:
    """Return total revenue for given date (YYYY-MM-DD)."""
    start_of_day, end_of_day = _day_window(date)
    async with Database().session() as s:
        res = (await s.execute(
            select(func.sum(BoughtGoods.price)).where(
                BoughtGoods.bought_datetime >= start_of_day,
                BoughtGoods.bought_datetime < end_of_day
            )
        )).scalar()
        return res or Decimal(0)


async def select_all_orders() -> Decimal:
    """Return total revenue for all time (sum of BoughtGoods.price)."""
    async with Database().session() as s:
        return (await s.execute(select(func.sum(BoughtGoods.price)))).scalar() or Decimal(0)


async def select_today_operations(date: str) -> Decimal:
    """Return total operations value for given date (YYYY-MM-DD)."""
    start_of_day, end_of_day = _day_window(date)
    async with Database().session() as s:
        res = (await s.execute(
            select(func.sum(Operations.operation_value)).where(
                Operations.operation_time >= start_of_day,
                Operations.operation_time < end_of_day
            )
        )).scalar()
        return res or Decimal(0)


async def select_all_operations() -> Decimal:
    """Return total operations value for all time."""
    async with Database().session() as s:
        return (await s.execute(select(func.sum(Operations.operation_value)))).scalar() or Decimal(0)


async def select_users_balance():
    """Return sum of all users' balances."""
    async with Database().session() as s:
        return (await s.execute(select(func.sum(User.balance)))).scalar()


async def select_user_operations(user_id: int | str) -> list[float]:
    """Return list of operation amounts for user."""
    async with Database().session() as s:
        result = await s.execute(
            select(Operations.operation_value).where(Operations.user_id == user_id)
        )
        return [row[0] for row in result.all()]


async def check_user_referrals(user_id: int) -> int:
    """Return count of referrals of the user."""
    async with Database().session() as s:
        return (await s.execute(
            select(func.count()).select_from(User).where(User.referral_id == user_id)
        )).scalar() or 0


async def get_user_referral(user_id: int) -> Optional[int]:
    """Return referral_id of the user or None."""
    async with Database().session() as s:
        result = await s.execute(select(User.referral_id).where(User.telegram_id == user_id))
        row = result.first()
        return row[0] if row else None


async def get_referral_earnings_stats(referrer_id: int) -> Dict:
    """Get statistics on user referral charges."""
    async with Database().session() as s:
        result = await s.execute(
            select(
                func.count(ReferralEarnings.id).label('total_earnings_count'),
                func.sum(ReferralEarnings.amount).label('total_amount'),
                func.sum(ReferralEarnings.original_amount).label('total_original_amount'),
                func.count(func.distinct(ReferralEarnings.referral_id)).label('active_referrals_count')
            ).where(ReferralEarnings.referrer_id == referrer_id)
        )
        stats = result.first()

        return {
            'total_earnings_count': stats.total_earnings_count or 0,
            'total_amount': stats.total_amount or Decimal(0),
            'total_original_amount': stats.total_original_amount or Decimal(0),
            'active_referrals_count': stats.active_referrals_count or 0
        }


async def get_one_referral_earning(earning_id: int) -> dict | None:
    """Get one user referral earning info."""
    async with Database().session() as s:
        result = await s.execute(select(ReferralEarnings).where(ReferralEarnings.id == earning_id))
        obj = result.scalars().first()
        return _obj_to_dict(obj, ReferralEarnings) if obj else None


# --- Cached versions ---

@async_cached(ttl=600, key_prefix="user")
async def check_user_cached(telegram_id: int | str):
    """Cached version of check_user"""
    return await check_user(telegram_id)


@async_cached(ttl=300, key_prefix="role")
async def check_role_cached(telegram_id: int):
    """Cached Role Verification"""
    return await check_role(telegram_id)


@async_cached(ttl=1800, key_prefix="category")
async def check_category_cached(category_name: str):
    """Cached Category Check"""
    return await check_category(category_name)


@async_cached(ttl=900, key_prefix="item_info")
async def get_item_info_cached(item_name: str):
    """Cached product information"""
    return await get_item_info(item_name)


@async_cached(ttl=300, key_prefix="item_values")
async def select_item_values_amount_cached(item_name: str):
    """Cached quantity of goods"""
    return await select_item_values_amount(item_name)


@async_cached(ttl=60, key_prefix="user_count")
async def get_user_count_cached():
    """Cached number of users"""
    return await get_user_count()


@async_cached(ttl=60, key_prefix="admin_count")
async def select_admins_cached():
    """Cached number of admins"""
    return await select_admins()


# Cache invalidation functions
async def invalidate_user_cache(user_id: int):
    """Invalidate user cache"""
    cache = get_cache_manager()
    if cache:
        await cache.delete(f"user:{user_id}")
        await cache.delete(f"role:{user_id}")
        await cache.invalidate_pattern(f"user_stats:{user_id}:*")
        await cache.invalidate_pattern(f"user_items:{user_id}:*")


async def invalidate_item_cache(item_name: str, category_name: str = None):
    """Invalidate product cache"""
    cache = get_cache_manager()
    if cache:
        await cache.delete(f"item:{item_name}")
        await cache.delete(f"item_info:{item_name}")
        await cache.delete(f"item_values:{item_name}")
        if category_name:
            await cache.delete(f"category:{category_name}")
        else:
            await cache.invalidate_pattern("category:*")


async def invalidate_category_cache(category_name: str):
    """Invalidate category cache"""
    cache = get_cache_manager()
    if cache:
        await cache.delete(f"category:{category_name}")
        await cache.invalidate_pattern(f"category_items:{category_name}:*")


async def invalidate_stats_cache():
    """Invalidate the entire statistics cache"""
    cache = get_cache_manager()
    if cache:
        await cache.invalidate_pattern("stats:*")
        await cache.delete("user_count")
        await cache.delete("admin_count")
