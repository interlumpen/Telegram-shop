import datetime
from decimal import Decimal

from bot.database.main import Database
from bot.database.models.main import Operations, ReferralEarnings


async def add_operation(user_id: int, value, operation_time=None) -> None:
    """Insert one balance operation row."""
    async with Database().session() as s:
        s.add(Operations(
            user_id=user_id,
            operation_value=value,
            operation_time=operation_time or datetime.datetime.now(datetime.timezone.utc),
        ))


async def add_referral_earning(referrer_id: int, referral_id: int, amount, original_amount) -> None:
    """Insert one referral earning row."""
    async with Database().session() as s:
        s.add(ReferralEarnings(
            referrer_id=referrer_id,
            referral_id=referral_id,
            amount=Decimal(str(amount)),
            original_amount=Decimal(str(original_amount)),
        ))
