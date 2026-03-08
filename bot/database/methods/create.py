from datetime import datetime
from decimal import Decimal

from sqlalchemy import select, exists

from bot.database.models import User, ItemValues, Goods, Categories, Operations, Payments, ReferralEarnings, Role
from bot.database import Database
from bot.database.methods.cache_utils import safe_create_task
from bot.database.methods.read import invalidate_stats_cache


async def create_user(telegram_id: int, registration_date: datetime, referral_id: int | None, role: int = 1) -> None:
    """Create user if missing; commit."""
    async with Database().session() as s:
        result = await s.execute(select(exists().where(User.telegram_id == telegram_id)))
        if result.scalar():
            return
        s.add(
            User(
                telegram_id=telegram_id,
                role_id=role,
                registration_date=registration_date,
                referral_id=referral_id,
            )
        )


async def create_item(item_name: str, item_description: str, item_price: int, category_name: str) -> None:
    """Insert item (goods); commit. Resolves category_name to category_id."""
    async with Database().session() as s:
        result = await s.execute(select(exists().where(Goods.name == item_name)))
        if result.scalar():
            return
        cat = (await s.execute(select(Categories.id).where(Categories.name == category_name))).scalar()
        if not cat:
            return
        s.add(
            Goods(
                name=item_name,
                description=item_description,
                price=item_price,
                category_id=cat,
            )
        )

    safe_create_task(invalidate_stats_cache())


async def add_values_to_item(item_name: str, value: str, is_infinity: bool) -> bool:
    """Add item value if not duplicate; True if inserted. Resolves item_name to item_id."""
    value_norm = (value or "").strip()
    if not value_norm:
        return False

    async with Database().session() as s:
        item_id = (await s.execute(select(Goods.id).where(Goods.name == item_name))).scalar()
        if not item_id:
            return False

        dup = (await s.execute(
            select(exists().where(
                ItemValues.item_id == item_id,
                ItemValues.value == value_norm,
            ))
        )).scalar()
        if dup:
            return False

        try:
            s.add(ItemValues(item_id=item_id, value=value_norm, is_infinity=bool(is_infinity)))
            await s.flush()
            return True
        except Exception:
            return False


async def create_category(category_name: str) -> None:
    """Insert category; commit."""
    async with Database().session() as s:
        result = await s.execute(select(exists().where(Categories.name == category_name)))
        if result.scalar():
            return
        s.add(Categories(name=category_name))

    safe_create_task(invalidate_stats_cache())


async def create_operation(user_id: int, value: int, operation_time: datetime) -> None:
    """Record completed balance operation; commit."""
    async with Database().session() as s:
        s.add(Operations(user_id, value, operation_time))


async def create_pending_payment(provider: str, external_id: str, user_id: int, amount: int, currency: str) -> None:
    """Create pending payment."""
    async with Database().session() as s:
        s.add(Payments(
            provider=provider,
            external_id=external_id,
            user_id=user_id,
            amount=Decimal(amount),
            currency=currency,
            status="pending"
        ))


async def create_referral_earning(referrer_id: int, referral_id: int, amount: int, original_amount: int) -> None:
    """Create a referral credit record."""
    async with Database().session() as s:
        s.add(
            ReferralEarnings(
                referrer_id=referrer_id,
                referral_id=referral_id,
                amount=Decimal(amount),
                original_amount=Decimal(original_amount)
            )
        )


async def create_role(name: str, permissions: int) -> int | None:
    """Create a new role. Returns the new role ID, or None if name conflict."""
    async with Database().session() as s:
        result = await s.execute(select(exists().where(Role.name == name)))
        if result.scalar():
            return None
        role = Role(name=name, permissions=permissions)
        s.add(role)
        await s.flush()
        return role.id
