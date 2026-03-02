from datetime import datetime
from decimal import Decimal

from sqlalchemy import exists
from sqlalchemy.exc import IntegrityError

from bot.database.models import User, ItemValues, Goods, Categories, Operations, Payments, ReferralEarnings
from bot.database import Database
from bot.database.main import run_sync
from bot.database.methods.cache_utils import safe_create_task
from bot.database.methods.read import invalidate_stats_cache


def _create_user(telegram_id: int, registration_date: datetime, referral_id: int | None, role: int = 1) -> None:
    """Create user if missing; commit."""
    with Database().session() as s:
        if s.query(exists().where(User.telegram_id == telegram_id)).scalar():
            return
        s.add(
            User(
                telegram_id=telegram_id,
                role_id=role,
                registration_date=registration_date,
                referral_id=referral_id,
            )
        )


def _create_item(item_name: str, item_description: str, item_price: int, category_name: str) -> None:
    """Insert item (goods); commit. Resolves category_name to category_id."""
    with Database().session() as s:
        if s.query(exists().where(Goods.name == item_name)).scalar():
            return
        cat = s.query(Categories.id).filter(Categories.name == category_name).scalar()
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


def _add_values_to_item(item_name: str, value: str, is_infinity: bool) -> bool:
    """Add item value if not duplicate; True if inserted. Resolves item_name to item_id."""
    value_norm = (value or "").strip()
    if not value_norm:
        return False

    with Database().session() as s:
        item_id = s.query(Goods.id).filter(Goods.name == item_name).scalar()
        if not item_id:
            return False

        if s.query(
                exists().where(
                    ItemValues.item_id == item_id,
                    ItemValues.value == value_norm
                )
        ).scalar():
            return False

        try:
            s.add(ItemValues(item_id=item_id, value=value_norm, is_infinity=bool(is_infinity)))
            return True
        except IntegrityError:
            return False


def _create_category(category_name: str) -> None:
    """Insert category; commit."""
    with Database().session() as s:
        if s.query(exists().where(Categories.name == category_name)).scalar():
            return
        s.add(Categories(name=category_name))

    safe_create_task(invalidate_stats_cache())


def _create_operation(user_id: int, value: int, operation_time: datetime) -> None:
    """Record completed balance operation; commit."""
    with Database().session() as s:
        s.add(Operations(user_id, value, operation_time))


def _create_pending_payment(provider: str, external_id: str, user_id: int, amount: int, currency: str) -> None:
    """Create pending payment."""
    with Database().session() as s:
        s.add(Payments(
            provider=provider,
            external_id=external_id,
            user_id=user_id,
            amount=Decimal(amount),
            currency=currency,
            status="pending"
        ))


def _create_referral_earning(referrer_id: int, referral_id: int, amount: int, original_amount: int) -> None:
    """Create a referral credit record."""
    with Database().session() as s:
        s.add(
            ReferralEarnings(
                referrer_id=referrer_id,
                referral_id=referral_id,
                amount=Decimal(amount),
                original_amount=Decimal(original_amount)
            )
        )


# Async public API
create_user = run_sync(_create_user)
create_item = run_sync(_create_item)
add_values_to_item = run_sync(_add_values_to_item)
create_category = run_sync(_create_category)
create_operation = run_sync(_create_operation)
create_pending_payment = run_sync(_create_pending_payment)
create_referral_earning = run_sync(_create_referral_earning)
