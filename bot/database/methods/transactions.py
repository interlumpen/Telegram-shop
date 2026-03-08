from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from bot.database.models import User, ItemValues, Goods, BoughtGoods, Payments, Operations
from bot.database import Database
from bot.misc import EnvKeys
from bot.database.methods.read import invalidate_user_cache, invalidate_stats_cache
from bot.database.methods.cache_utils import safe_create_task
from bot.database.methods.audit import log_audit


async def buy_item_transaction(telegram_id: int, item_name: str) -> tuple[bool, str, dict | None]:
    """
    Complete transactional purchase of goods with checks and locks.
    Returns: (success, message, purchase_data)
    """
    async with Database().session() as s:
        try:
            # 1. Lock the user to check the balance
            user = (await s.execute(
                select(User).where(User.telegram_id == telegram_id).with_for_update()
            )).scalars().one_or_none()

            if not user:
                await s.rollback()
                return False, "user_not_found", None

            # 2. Get information about the product
            goods = (await s.execute(
                select(Goods).where(Goods.name == item_name).with_for_update()
            )).scalars().one_or_none()

            if not goods:
                await s.rollback()
                return False, "item_not_found", None

            price = Decimal(str(goods.price))

            # 3. Checking the balance
            if user.balance < price:
                await s.rollback()
                return False, "insufficient_funds", None

            # 4. Receive and lock the goods for purchase
            item_value = (await s.execute(
                select(ItemValues).where(ItemValues.item_id == goods.id).with_for_update(skip_locked=True)
            )).scalars().first()

            if not item_value:
                await s.rollback()
                return False, "out_of_stock", None

            # 5. If the product is not endless, we remove it
            if not item_value.is_infinity:
                await s.delete(item_value)

            # 6. Write off the balance
            user.balance -= price

            # 7. Create a purchase record
            bought_item = BoughtGoods(
                name=item_name,
                value=item_value.value,
                price=price,
                buyer_id=telegram_id,
                bought_datetime=datetime.now(timezone.utc),
                unique_id=uuid4().int >> 65
            )
            s.add(bought_item)

            # 8. Commit the transaction
            await s.commit()

            safe_create_task(invalidate_user_cache(telegram_id))
            safe_create_task(invalidate_stats_cache())

            return True, "success", {
                "item_name": item_name,
                "value": item_value.value,
                "price": float(price),
                "new_balance": float(user.balance),
                "unique_id": bought_item.unique_id
            }

        except Exception as e:
            await s.rollback()
            await log_audit(
                "purchase_failed",
                level="WARNING",
                user_id=telegram_id,
                resource_type="Item",
                resource_id=item_name,
                details=str(e),
            )
            return False, "transaction_error", None


async def process_payment_with_referral(
        user_id: int,
        amount: Decimal,
        provider: str,
        external_id: str,
        referral_percent: int = 0
) -> tuple[bool, str]:
    """
    Processing a payment with a referral bonus in one transaction.
    Returns (success, message)
    """

    async with Database().session() as s:
        try:
            # 1. Check the idempotency of the payment
            existing_payment = (await s.execute(
                select(Payments).where(
                    Payments.provider == provider,
                    Payments.external_id == external_id
                ).with_for_update()
            )).scalars().first()

            if existing_payment:
                if existing_payment.status == "succeeded":
                    await s.rollback()
                    return False, "already_processed"
                existing_payment.status = "succeeded"
            else:
                payment = Payments(
                    provider=provider,
                    external_id=external_id,
                    user_id=user_id,
                    amount=amount,
                    currency=EnvKeys.PAY_CURRENCY,
                    status="succeeded"
                )
                s.add(payment)

            # 2. Update the user's balance
            user = (await s.execute(
                select(User).where(User.telegram_id == user_id).with_for_update()
            )).scalars().one()

            user.balance += amount

            # 3. Create a transaction record
            operation = Operations(
                user_id=user_id,
                operation_value=amount,
                operation_time=datetime.now(timezone.utc)
            )
            s.add(operation)

            # 4. Process the referral bonus
            if referral_percent > 0 and user.referral_id and user.referral_id != user_id:
                referral_amount = (Decimal(referral_percent) / Decimal(100)) * amount

                if referral_amount > 0:
                    referrer = (await s.execute(
                        select(User).where(User.telegram_id == user.referral_id).with_for_update()
                    )).scalars().one_or_none()

                    if referrer:
                        referrer.balance += referral_amount
                        await log_audit(
                            "referral_bonus",
                            user_id=user.referral_id,
                            resource_type="User",
                            resource_id=str(user_id),
                            details=f"paid={amount}, bonus={referral_amount}",
                        )

                        from bot.database.models import ReferralEarnings
                        earning = ReferralEarnings(
                            referrer_id=user.referral_id,
                            referral_id=user_id,
                            amount=referral_amount,
                            original_amount=amount
                        )
                        s.add(earning)

            referrer_id = user.referral_id if referral_percent > 0 else None

            await s.commit()

            safe_create_task(invalidate_user_cache(user_id))
            safe_create_task(invalidate_stats_cache())
            if referrer_id:
                safe_create_task(invalidate_user_cache(referrer_id))

            return True, "success"

        except IntegrityError:
            await s.rollback()
            return False, "already_processed"

        except Exception as e:
            await s.rollback()
            await log_audit(
                "payment_failed",
                level="WARNING",
                user_id=user_id,
                resource_type="Payment",
                details=f"provider={provider}, amount={amount}, error={e}",
            )
            return False, "payment_error"


async def admin_balance_change(telegram_id: int, amount: int) -> tuple[bool, str]:
    """
    Atomic admin balance change (top-up or deduction) with operation record.
    amount > 0 for top-up, amount < 0 for deduction.
    Returns (success, message).
    Raises ValueError if insufficient funds for deduction.
    """
    async with Database().session() as s:
        try:
            user = (await s.execute(
                select(User).where(User.telegram_id == telegram_id).with_for_update()
            )).scalars().one_or_none()

            if not user:
                await s.rollback()
                return False, "user_not_found"

            if amount < 0 and user.balance < abs(amount):
                await s.rollback()
                raise ValueError("insufficient_funds")

            user.balance += amount

            operation = Operations(
                user_id=telegram_id,
                operation_value=amount,
                operation_time=datetime.now(timezone.utc)
            )
            s.add(operation)

            await s.commit()

            safe_create_task(invalidate_user_cache(telegram_id))
            safe_create_task(invalidate_stats_cache())

            return True, "success"

        except ValueError:
            raise

        except Exception as e:
            await s.rollback()
            await log_audit(
                "admin_balance_change_failed",
                level="WARNING",
                user_id=telegram_id,
                resource_type="User",
                details=f"amount={amount}, error={e}",
            )
            return False, "balance_change_error"
