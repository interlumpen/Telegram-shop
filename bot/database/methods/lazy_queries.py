import asyncio
from typing import Any
from sqlalchemy import func, desc
from bot.database import Database
from bot.database.models import (
    Categories, Goods, User, BoughtGoods, ItemValues,
    ReferralEarnings, Role
)


def _run_in_executor(func, *args, **kwargs):
    """Helper to run a sync callable in the default executor."""
    loop = asyncio.get_running_loop()
    return loop.run_in_executor(None, lambda: func(*args, **kwargs))


def _query_categories_sync(offset: int = 0, limit: int = 10, count_only: bool = False) -> Any:
    with Database().session() as s:
        if count_only:
            return s.query(func.count(Categories.id)).scalar() or 0
        return [row[0] for row in s.query(Categories.name)
        .order_by(Categories.name.asc())
        .offset(offset)
        .limit(limit)
        .all()]


def _query_items_in_category_sync(category_name: str, offset: int = 0, limit: int = 10,
                                  count_only: bool = False) -> Any:
    with Database().session() as s:
        cat_id = s.query(Categories.id).filter(Categories.name == category_name).scalar()
        if not cat_id:
            return 0 if count_only else []
        query = s.query(Goods.name).filter(Goods.category_id == cat_id)
        if count_only:
            return query.count()
        return [row[0] for row in query
        .order_by(Goods.name.asc())
        .offset(offset)
        .limit(limit)
        .all()]


def _query_user_bought_items_sync(user_id: int, offset: int = 0, limit: int = 10, count_only: bool = False) -> Any:
    with Database().session() as s:
        query = s.query(BoughtGoods).filter(BoughtGoods.buyer_id == user_id)
        if count_only:
            return query.count()
        return query.order_by(desc(BoughtGoods.bought_datetime)) \
            .offset(offset) \
            .limit(limit) \
            .all()


def _query_all_users_sync(offset: int = 0, limit: int = 10, count_only: bool = False) -> Any:
    with Database().session() as s:
        if count_only:
            return s.query(func.count(User.telegram_id)).scalar() or 0
        return [row[0] for row in s.query(User.telegram_id)
        .order_by(User.telegram_id.asc())
        .offset(offset)
        .limit(limit)
        .all()]


def _query_admins_sync(offset: int = 0, limit: int = 10, count_only: bool = False) -> Any:
    with Database().session() as s:
        query = s.query(User.telegram_id).join(Role).filter(Role.name == 'ADMIN')
        if count_only:
            return query.count()
        return [row[0] for row in query
        .order_by(User.telegram_id.asc())
        .offset(offset)
        .limit(limit)
        .all()]


def _query_items_in_position_sync(item_name: str, offset: int = 0, limit: int = 10, count_only: bool = False) -> Any:
    with Database().session() as s:
        item_id = s.query(Goods.id).filter(Goods.name == item_name).scalar()
        if not item_id:
            return 0 if count_only else []
        query = s.query(ItemValues.id).filter(ItemValues.item_id == item_id)
        if count_only:
            return query.count()
        return [row[0] for row in query
        .order_by(ItemValues.id.asc())
        .offset(offset)
        .limit(limit)
        .all()]


def _query_user_referrals_sync(user_id: int, offset: int = 0, limit: int = 10, count_only: bool = False) -> Any:
    with Database().session() as s:
        if count_only:
            return s.query(func.count(User.telegram_id)).filter(User.referral_id == user_id).scalar() or 0

        # Subquery for per-referral earnings
        earnings_subq = (
            s.query(
                ReferralEarnings.referral_id,
                func.coalesce(func.sum(ReferralEarnings.amount), 0).label('total_earned')
            )
            .filter(ReferralEarnings.referrer_id == user_id)
            .group_by(ReferralEarnings.referral_id)
            .subquery()
        )

        rows = (
            s.query(
                User.telegram_id,
                User.registration_date,
                func.coalesce(earnings_subq.c.total_earned, 0).label('total_earned')
            )
            .outerjoin(earnings_subq, User.telegram_id == earnings_subq.c.referral_id)
            .filter(User.referral_id == user_id)
            .offset(offset)
            .limit(limit)
            .all()
        )

        result = [
            {
                'telegram_id': row.telegram_id,
                'registration_date': row.registration_date,
                'total_earned': row.total_earned
            }
            for row in rows
        ]

        return sorted(result, key=lambda x: x['total_earned'], reverse=True)


def _query_referral_earnings_from_user_sync(referrer_id: int, referral_id: int, offset: int = 0, limit: int = 10,
                                            count_only: bool = False) -> Any:
    with Database().session() as s:
        query = s.query(ReferralEarnings).filter(
            ReferralEarnings.referrer_id == referrer_id,
            ReferralEarnings.referral_id == referral_id
        )
        if count_only:
            return query.count()
        return query.order_by(desc(ReferralEarnings.created_at)) \
            .offset(offset) \
            .limit(limit) \
            .all()


def _query_all_referral_earnings_sync(referrer_id: int, offset: int = 0, limit: int = 10,
                                      count_only: bool = False) -> Any:
    with Database().session() as s:
        query = s.query(ReferralEarnings).filter(
            ReferralEarnings.referrer_id == referrer_id
        )
        if count_only:
            return query.count()
        return query.order_by(desc(ReferralEarnings.created_at)) \
            .offset(offset) \
            .limit(limit) \
            .all()


# Async public API

async def query_categories(offset: int = 0, limit: int = 10, count_only: bool = False) -> Any:
    """Query categories with pagination"""
    return await _run_in_executor(_query_categories_sync, offset, limit, count_only)


async def query_items_in_category(category_name: str, offset: int = 0, limit: int = 10,
                                  count_only: bool = False) -> Any:
    """Query items in category with pagination"""
    return await _run_in_executor(_query_items_in_category_sync, category_name, offset, limit, count_only)


async def query_user_bought_items(user_id: int, offset: int = 0, limit: int = 10, count_only: bool = False) -> Any:
    """Query user's bought items with pagination"""
    return await _run_in_executor(_query_user_bought_items_sync, user_id, offset, limit, count_only)


async def query_all_users(offset: int = 0, limit: int = 10, count_only: bool = False) -> Any:
    """Query all users with pagination"""
    return await _run_in_executor(_query_all_users_sync, offset, limit, count_only)


async def query_admins(offset: int = 0, limit: int = 10, count_only: bool = False) -> Any:
    """Query admin users with pagination"""
    return await _run_in_executor(_query_admins_sync, offset, limit, count_only)


async def query_items_in_position(item_name: str, offset: int = 0, limit: int = 10, count_only: bool = False) -> Any:
    """Query items in position with pagination"""
    return await _run_in_executor(_query_items_in_position_sync, item_name, offset, limit, count_only)


async def query_user_referrals(user_id: int, offset: int = 0, limit: int = 10, count_only: bool = False) -> Any:
    """Query user's referrals with earnings info"""
    return await _run_in_executor(_query_user_referrals_sync, user_id, offset, limit, count_only)


async def query_referral_earnings_from_user(referrer_id: int, referral_id: int, offset: int = 0, limit: int = 10,
                                            count_only: bool = False) -> Any:
    """Query earnings from specific referral"""
    return await _run_in_executor(_query_referral_earnings_from_user_sync, referrer_id, referral_id, offset, limit, count_only)


async def query_all_referral_earnings(referrer_id: int, offset: int = 0, limit: int = 10,
                                      count_only: bool = False) -> Any:
    """Query all referral earnings for user"""
    return await _run_in_executor(_query_all_referral_earnings_sync, referrer_id, offset, limit, count_only)
