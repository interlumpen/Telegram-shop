import asyncio
import datetime
from decimal import Decimal
from functools import wraps
from typing import Optional, Dict, TypeVar, Callable, Any, Coroutine

from sqlalchemy import func, exists

from bot.database.models import Database, User, ItemValues, Goods, Categories, Role, BoughtGoods, \
    Operations, ReferralEarnings
from bot.database.main import run_sync
from bot.misc.caching import get_cache_manager

F = TypeVar('F', bound=Callable[..., Any])


# Wrapper for synchronous functions to asynchronous functions with caching
def async_cached(ttl: int = 300, key_prefix: str = "") -> Callable[[F], Callable[..., Coroutine[Any, Any, Any]]]:
    def decorator(sync_func: F) -> Callable[..., Coroutine[Any, Any, Any]]:
        @wraps(sync_func)
        async def async_wrapper(*args, **kwargs):
            # Generate the cache key
            cache_key = f"{key_prefix or sync_func.__name__}:{':'.join(str(arg) for arg in args)}"

            cache = get_cache_manager()
            if cache:
                # Trying to get it from the cache
                cached_value = await cache.get(cache_key)
                if cached_value is not None:
                    return cached_value

            # Execute synchronous function in executor
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, sync_func, *args)

            # Save to cache
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


# --- Sync implementations (private) ---

def _check_user(telegram_id: int | str) -> Optional[dict]:
    """Return user by Telegram ID or None if not found."""
    with Database().session() as s:
        result = s.query(User).filter(User.telegram_id == telegram_id).one_or_none()
        return result.__dict__ if result else None


def _check_role(telegram_id: int) -> int:
    """Return permission bitmask for user (0 if none)."""
    with Database().session() as s:
        role_id = s.query(User.role_id).filter(User.telegram_id == telegram_id).scalar()
        if not role_id:
            return 0
        perms = s.query(Role.permissions).filter(Role.id == role_id).scalar()
        return perms or 0


def _get_role_id_by_name(role_name: str) -> Optional[int]:
    """Return role id by name or None."""
    with Database().session() as s:
        return s.query(Role.id).filter(Role.name == role_name).scalar()


def _check_role_name_by_id(role_id: int) -> str:
    """Return role name by id (raises if not found)."""
    with Database().session() as s:
        return s.query(Role.name).filter(Role.id == role_id).one()[0]


def _select_max_role_id() -> Optional[int]:
    """Return role_id with the highest permissions value."""
    with Database().session() as s:
        result = s.query(Role.id).order_by(Role.permissions.desc()).first()
        return result[0] if result else None


def _get_all_roles() -> list[dict]:
    """Return all roles as list of dicts ordered by permissions asc."""
    with Database().session() as s:
        roles = s.query(Role).order_by(Role.permissions.asc()).all()
        return [{'id': r.id, 'name': r.name, 'permissions': r.permissions, 'default': r.default} for r in roles]


def _get_role_by_id(role_id: int) -> dict | None:
    """Return single role as dict or None."""
    with Database().session() as s:
        r = s.query(Role).filter(Role.id == role_id).first()
        return {'id': r.id, 'name': r.name, 'permissions': r.permissions, 'default': r.default} if r else None


def _get_roles_with_max_perms(max_perms: int) -> list[dict]:
    """Return roles where permissions <= max_perms, ordered by permissions ascending."""
    with Database().session() as s:
        roles = s.query(Role).filter(Role.permissions <= max_perms).order_by(Role.permissions.asc()).all()
        return [{'id': r.id, 'name': r.name, 'permissions': r.permissions, 'default': r.default} for r in roles]


def _count_users_with_role(role_id: int) -> int:
    """Return count of users assigned to a given role."""
    with Database().session() as s:
        return s.query(func.count(User.telegram_id)).filter(User.role_id == role_id).scalar() or 0


def _select_today_users(date: str) -> int:
    """Return count of users registered on given date (YYYY-MM-DD)."""
    start_of_day, end_of_day = _day_window(date)
    with Database().session() as s:
        return s.query(User).filter(
            User.registration_date >= start_of_day,
            User.registration_date < end_of_day
        ).count()


def _get_user_count() -> int:
    """Return total users count."""
    with Database().session() as s:
        return s.query(User).count()


def _select_admins() -> int:
    """Return count of users with role_id > 1."""
    with Database().session() as s:
        return s.query(func.count(User.telegram_id)).filter(User.role_id > 1).scalar() or 0


def _get_all_users() -> list[tuple[int]]:
    """Return list of all user telegram_ids (as tuples)."""
    with Database().session() as s:
        return s.query(User.telegram_id).all()


def _get_bought_item_info(item_id: str) -> dict | None:
    """Return bought item row as dict by row id, or None."""
    with Database().session() as s:
        result = s.query(BoughtGoods).filter(BoughtGoods.id == item_id).first()
        return result.__dict__ if result else None


def _get_item_info(item_name: str) -> dict | None:
    """Return item (position) row as dict by name, or None."""
    with Database().session() as s:
        result = s.query(Goods).filter(Goods.name == item_name).first()
        return result.__dict__ if result else None


def _get_goods_info(item_id: int) -> dict | None:
    """Return item_value row as dict by id, including item_name from Goods."""
    with Database().session() as s:
        result = s.query(ItemValues).filter(ItemValues.id == int(item_id)).first()
        if not result:
            return None
        d = result.__dict__.copy()
        # Resolve item_name from Goods for display
        item = s.query(Goods.name).filter(Goods.id == result.item_id).scalar()
        d['item_name'] = item
        return d


def _check_category(category_name: str) -> dict | None:
    """Return category as dict by name, or None."""
    with Database().session() as s:
        result = s.query(Categories).filter(Categories.name == category_name).first()
        return result.__dict__ if result else None


def _select_item_values_amount(item_name: str) -> int:
    """Return count of item_values for an item (by item name)."""
    with Database().session() as s:
        item = s.query(Goods.id).filter(Goods.name == item_name).scalar()
        if not item:
            return 0
        return s.query(func.count()).filter(ItemValues.item_id == item).scalar() or 0


def _check_value(item_name: str) -> bool:
    """Return True if item has any infinite value (is_infinity=True)."""
    with Database().session() as s:
        item = s.query(Goods.id).filter(Goods.name == item_name).scalar()
        if not item:
            return False
        return s.query(
            exists().where(
                ItemValues.item_id == item,
                ItemValues.is_infinity.is_(True),
            )
        ).scalar()


def _select_user_items(buyer_id: int | str) -> int:
    """Return count of bought items for user."""
    with Database().session() as s:
        return s.query(func.count()).filter(BoughtGoods.buyer_id == buyer_id).scalar() or 0


def _select_bought_item(unique_id: int) -> dict | None:
    """Return one bought item by unique_id as dict, or None."""
    with Database().session() as s:
        result = s.query(BoughtGoods).filter(BoughtGoods.unique_id == unique_id).first()
        return result.__dict__ if result else None


def _select_count_items() -> int:
    """Return total count of item_values."""
    with Database().session() as s:
        return s.query(ItemValues).count()


def _select_count_goods() -> int:
    """Return total count of goods (positions)."""
    with Database().session() as s:
        return s.query(Goods).count()


def _select_count_categories() -> int:
    """Return total count of categories."""
    with Database().session() as s:
        return s.query(Categories).count()


def _select_count_bought_items() -> int:
    """Return total count of bought items."""
    with Database().session() as s:
        return s.query(BoughtGoods).count()


def _select_today_orders(date: str) -> Decimal:
    """Return total revenue for given date (YYYY-MM-DD)."""
    start_of_day, end_of_day = _day_window(date)
    with Database().session() as s:
        res = (
            s.query(func.sum(BoughtGoods.price))
            .filter(
                BoughtGoods.bought_datetime >= start_of_day,
                BoughtGoods.bought_datetime < end_of_day
            )
            .scalar()
        )
        return res or Decimal(0)


def _select_all_orders() -> Decimal:
    """Return total revenue for all time (sum of BoughtGoods.price)."""
    with Database().session() as s:
        return s.query(func.sum(BoughtGoods.price)).scalar() or Decimal(0)


def _select_today_operations(date: str) -> Decimal:
    """Return total operations value for given date (YYYY-MM-DD)."""
    start_of_day, end_of_day = _day_window(date)
    with Database().session() as s:
        res = (
            s.query(func.sum(Operations.operation_value))
            .filter(
                Operations.operation_time >= start_of_day,
                Operations.operation_time < end_of_day
            )
            .scalar()
        )
        return res or Decimal(0)


def _select_all_operations() -> Decimal:
    """Return total operations value for all time."""
    with Database().session() as s:
        return s.query(func.sum(Operations.operation_value)).scalar() or Decimal(0)


def _select_users_balance():
    """Return sum of all users' balances."""
    with Database().session() as s:
        return s.query(func.sum(User.balance)).scalar()


def _select_user_operations(user_id: int | str) -> list[float]:
    """Return list of operation amounts for user."""
    with Database().session() as s:
        return [row[0] for row in s.query(Operations.operation_value).filter(Operations.user_id == user_id).all()]


def _check_user_referrals(user_id: int) -> int:
    """Return count of referrals of the user."""
    with Database().session() as s:
        return s.query(User).filter(User.referral_id == user_id).count()


def _get_user_referral(user_id: int) -> Optional[int]:
    """Return referral_id of the user or None."""
    with Database().session() as s:
        result = s.query(User.referral_id).filter(User.telegram_id == user_id).first()
        return result[0] if result else None


def _get_referral_earnings_stats(referrer_id: int) -> Dict:
    """Get statistics on user referral charges."""
    with Database().session() as s:
        stats = s.query(
            func.count(ReferralEarnings.id).label('total_earnings_count'),
            func.sum(ReferralEarnings.amount).label('total_amount'),
            func.sum(ReferralEarnings.original_amount).label('total_original_amount'),
            func.count(func.distinct(ReferralEarnings.referral_id)).label('active_referrals_count')
        ).filter(
            ReferralEarnings.referrer_id == referrer_id
        ).first()

        return {
            'total_earnings_count': stats.total_earnings_count or 0,
            'total_amount': stats.total_amount or Decimal(0),
            'total_original_amount': stats.total_original_amount or Decimal(0),
            'active_referrals_count': stats.active_referrals_count or 0
        }


def _get_one_referral_earning(earning_id: int) -> dict | None:
    """Get one user referral earning info."""
    with Database().session() as s:
        result = s.query(ReferralEarnings).filter(ReferralEarnings.id == earning_id).first()
        return result.__dict__ if result else None


# Async public API (run in executor)

check_user = run_sync(_check_user)
check_role = run_sync(_check_role)
get_role_id_by_name = run_sync(_get_role_id_by_name)
check_role_name_by_id = run_sync(_check_role_name_by_id)
select_max_role_id = run_sync(_select_max_role_id)
get_all_roles = run_sync(_get_all_roles)
get_role_by_id = run_sync(_get_role_by_id)
get_roles_with_max_perms = run_sync(_get_roles_with_max_perms)
count_users_with_role = run_sync(_count_users_with_role)
select_today_users = run_sync(_select_today_users)
get_user_count = run_sync(_get_user_count)
select_admins = run_sync(_select_admins)
get_all_users = run_sync(_get_all_users)
get_bought_item_info = run_sync(_get_bought_item_info)
get_item_info = run_sync(_get_item_info)
get_goods_info = run_sync(_get_goods_info)
check_category = run_sync(_check_category)
select_item_values_amount = run_sync(_select_item_values_amount)
check_value = run_sync(_check_value)
select_user_items = run_sync(_select_user_items)
select_bought_item = run_sync(_select_bought_item)
select_count_items = run_sync(_select_count_items)
select_count_goods = run_sync(_select_count_goods)
select_count_categories = run_sync(_select_count_categories)
select_count_bought_items = run_sync(_select_count_bought_items)
select_today_orders = run_sync(_select_today_orders)
select_all_orders = run_sync(_select_all_orders)
select_today_operations = run_sync(_select_today_operations)
select_all_operations = run_sync(_select_all_operations)
select_users_balance = run_sync(_select_users_balance)
select_user_operations = run_sync(_select_user_operations)
check_user_referrals = run_sync(_check_user_referrals)
get_user_referral = run_sync(_get_user_referral)
get_referral_earnings_stats = run_sync(_get_referral_earnings_stats)
get_one_referral_earning = run_sync(_get_one_referral_earning)


# --- Cached versions (cache + executor) ---

@async_cached(ttl=600, key_prefix="user")
def check_user_cached(telegram_id: int | str):
    """Cached version of check_user"""
    return _check_user(telegram_id)


@async_cached(ttl=300, key_prefix="role")
def check_role_cached(telegram_id: int):
    """Cached Role Verification"""
    return _check_role(telegram_id)


@async_cached(ttl=1800, key_prefix="category")
def check_category_cached(category_name: str):
    """Cached Category Check"""
    return _check_category(category_name)


@async_cached(ttl=900, key_prefix="item_info")
def get_item_info_cached(item_name: str):
    """Cached product information"""
    return _get_item_info(item_name)


@async_cached(ttl=300, key_prefix="item_values")
def select_item_values_amount_cached(item_name: str):
    """Cached quantity of goods"""
    return _select_item_values_amount(item_name)


@async_cached(ttl=60, key_prefix="user_count")
def get_user_count_cached():
    """Cached number of users"""
    return _get_user_count()


@async_cached(ttl=60, key_prefix="admin_count")
def select_admins_cached():
    """Cached number of admins"""
    return _select_admins()


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
        # Invalidate affected category (or all if unknown)
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
