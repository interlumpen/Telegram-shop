from typing import Any
from sqlalchemy import func, select
from sqlalchemy import desc
from bot.database import Database
from bot.database.models import (
    Categories, Goods, User, BoughtGoods, ItemValues,
    ReferralEarnings, Role
)


async def query_categories(offset: int = 0, limit: int = 10, count_only: bool = False) -> Any:
    """Query categories with pagination"""
    async with Database().session() as s:
        if count_only:
            return (await s.execute(select(func.count(Categories.id)))).scalar() or 0
        result = await s.execute(
            select(Categories.name)
            .order_by(Categories.name.asc())
            .offset(offset)
            .limit(limit)
        )
        return [row[0] for row in result.all()]


async def query_items_in_category(category_name: str, offset: int = 0, limit: int = 10,
                                  count_only: bool = False) -> Any:
    """Query items in category with pagination"""
    async with Database().session() as s:
        cat_id = (await s.execute(
            select(Categories.id).where(Categories.name == category_name)
        )).scalar()
        if not cat_id:
            return 0 if count_only else []
        query = select(Goods.name).where(Goods.category_id == cat_id)
        if count_only:
            count_result = await s.execute(select(func.count()).select_from(query.subquery()))
            return count_result.scalar() or 0
        result = await s.execute(
            query.order_by(Goods.name.asc()).offset(offset).limit(limit)
        )
        return [row[0] for row in result.all()]


async def query_user_bought_items(user_id: int, offset: int = 0, limit: int = 10, count_only: bool = False) -> Any:
    """Query user's bought items with pagination"""
    async with Database().session() as s:
        if count_only:
            return (await s.execute(
                select(func.count()).select_from(BoughtGoods).where(BoughtGoods.buyer_id == user_id)
            )).scalar() or 0
        result = await s.execute(
            select(BoughtGoods)
            .where(BoughtGoods.buyer_id == user_id)
            .order_by(desc(BoughtGoods.bought_datetime))
            .offset(offset)
            .limit(limit)
        )
        return result.scalars().all()


async def query_all_users(offset: int = 0, limit: int = 10, count_only: bool = False) -> Any:
    """Query all users with pagination"""
    async with Database().session() as s:
        if count_only:
            return (await s.execute(select(func.count(User.telegram_id)))).scalar() or 0
        result = await s.execute(
            select(User.telegram_id)
            .order_by(User.telegram_id.asc())
            .offset(offset)
            .limit(limit)
        )
        return [row[0] for row in result.all()]


async def query_items_in_position(item_name: str, offset: int = 0, limit: int = 10, count_only: bool = False) -> Any:
    """Query items in position with pagination"""
    async with Database().session() as s:
        item_id = (await s.execute(
            select(Goods.id).where(Goods.name == item_name)
        )).scalar()
        if not item_id:
            return 0 if count_only else []
        query = select(ItemValues.id).where(ItemValues.item_id == item_id)
        if count_only:
            count_result = await s.execute(select(func.count()).select_from(query.subquery()))
            return count_result.scalar() or 0
        result = await s.execute(
            query.order_by(ItemValues.id.asc()).offset(offset).limit(limit)
        )
        return [row[0] for row in result.all()]


async def query_user_referrals(user_id: int, offset: int = 0, limit: int = 10, count_only: bool = False) -> Any:
    """Query user's referrals with earnings info"""
    async with Database().session() as s:
        if count_only:
            return (await s.execute(
                select(func.count(User.telegram_id)).where(User.referral_id == user_id)
            )).scalar() or 0

        earnings_subq = (
            select(
                ReferralEarnings.referral_id,
                func.coalesce(func.sum(ReferralEarnings.amount), 0).label('total_earned')
            )
            .where(ReferralEarnings.referrer_id == user_id)
            .group_by(ReferralEarnings.referral_id)
            .subquery()
        )

        stmt = (
            select(
                User.telegram_id,
                User.registration_date,
                func.coalesce(earnings_subq.c.total_earned, 0).label('total_earned')
            )
            .outerjoin(earnings_subq, User.telegram_id == earnings_subq.c.referral_id)
            .where(User.referral_id == user_id)
            .order_by(desc(func.coalesce(earnings_subq.c.total_earned, 0)))
            .offset(offset)
            .limit(limit)
        )
        rows = (await s.execute(stmt)).all()

        return [
            {
                'telegram_id': row.telegram_id,
                'registration_date': row.registration_date,
                'total_earned': row.total_earned
            }
            for row in rows
        ]


async def query_referral_earnings_from_user(referrer_id: int, referral_id: int, offset: int = 0, limit: int = 10,
                                            count_only: bool = False) -> Any:
    """Query earnings from specific referral"""
    async with Database().session() as s:
        base = select(ReferralEarnings).where(
            ReferralEarnings.referrer_id == referrer_id,
            ReferralEarnings.referral_id == referral_id
        )
        if count_only:
            count_result = await s.execute(select(func.count()).select_from(base.subquery()))
            return count_result.scalar() or 0
        result = await s.execute(
            base.order_by(desc(ReferralEarnings.created_at)).offset(offset).limit(limit)
        )
        return result.scalars().all()


async def query_all_referral_earnings(referrer_id: int, offset: int = 0, limit: int = 10,
                                      count_only: bool = False) -> Any:
    """Query all referral earnings for user"""
    async with Database().session() as s:
        base = select(ReferralEarnings).where(
            ReferralEarnings.referrer_id == referrer_id
        )
        if count_only:
            count_result = await s.execute(select(func.count()).select_from(base.subquery()))
            return count_result.scalar() or 0
        result = await s.execute(
            base.order_by(desc(ReferralEarnings.created_at)).offset(offset).limit(limit)
        )
        return result.scalars().all()
