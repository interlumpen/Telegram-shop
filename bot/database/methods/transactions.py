from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from bot.database.models import User, ItemValues, Goods, BoughtGoods, Payments, Operations
from bot.database import Database
from bot.database.main import run_sync
from bot.misc import EnvKeys
from bot.database.methods.read import invalidate_user_cache, invalidate_stats_cache
from bot.database.methods.cache_utils import safe_create_task
from bot.database.methods.audit import log_audit


def _buy_item_transaction(telegram_id: int, item_name: str) -> tuple[bool, str, dict | None]:
    """
    Complete transactional purchase of goods with checks and locks.
    Returns: (success, message, purchase_data)
    """
    with Database().session() as s:
        try:
            # Starting the transaction
            s.begin()

            # 1. Block the user to check the balance
            user = s.query(User).filter(
                User.telegram_id == telegram_id
            ).with_for_update().one_or_none()

            if not user:
                s.rollback()
                return False, "user_not_found", None

            # 2. Get information about the product
            goods = s.query(Goods).filter(
                Goods.name == item_name
            ).with_for_update().one_or_none()

            if not goods:
                s.rollback()
                return False, "item_not_found", None

            price = Decimal(str(goods.price))

            # 3. Checking the balance
            if user.balance < price:
                s.rollback()
                return False, "insufficient_funds", None

            # 4. receive and block the goods for purchase
            item_value = s.query(ItemValues).filter(
                ItemValues.item_id == goods.id
            ).with_for_update(skip_locked=True).first()

            if not item_value:
                s.rollback()
                return False, "out_of_stock", None

            # 5. If the product is not endless, we remove it
            if not item_value.is_infinity:
                s.delete(item_value)

            # 6. Write off the balance
            user.balance -= price

            # 7. Create a purchase record
            bought_item = BoughtGoods(
                name=item_name,
                value=item_value.value,
                price=price,
                buyer_id=telegram_id,
                bought_datetime=datetime.now(timezone.utc),
                unique_id=uuid4().int >> 65  # 63-bit positive UUID-derived ID
            )
            s.add(bought_item)

            # 8. Commit the transaction
            s.commit()

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
            s.rollback()
            log_audit(
                "purchase_failed",
                level="WARNING",
                user_id=telegram_id,
                resource_type="Item",
                resource_id=item_name,
                details=str(e),
            )
            return False, "transaction_error", None


def _process_payment_with_referral(
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

    with Database().session() as s:
        try:
            s.begin()

            # 1. Check the idempotency of the payment
            existing_payment = s.query(Payments).filter(
                Payments.provider == provider,
                Payments.external_id == external_id
            ).with_for_update().first()

            if existing_payment:
                if existing_payment.status == "succeeded":
                    s.rollback()
                    return False, "already_processed"
                existing_payment.status = "succeeded"
            else:
                # Create a new payment record
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
            user = s.query(User).filter(
                User.telegram_id == user_id
            ).with_for_update().one()

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
                    # Update the referrer's balance
                    referrer = s.query(User).filter(
                        User.telegram_id == user.referral_id
                    ).with_for_update().one_or_none()

                    if referrer:
                        referrer.balance += referral_amount
                        log_audit(
                            "referral_bonus",
                            user_id=user.referral_id,
                            resource_type="User",
                            resource_id=str(user_id),
                            details=f"paid={amount}, bonus={referral_amount}",
                        )

                        # Create a referral credit record
                        from bot.database.models import ReferralEarnings
                        earning = ReferralEarnings(
                            referrer_id=user.referral_id,
                            referral_id=user_id,
                            amount=referral_amount,
                            original_amount=amount
                        )
                        s.add(earning)

            referrer_id = user.referral_id if referral_percent > 0 else None

            s.commit()

            safe_create_task(invalidate_user_cache(user_id))
            safe_create_task(invalidate_stats_cache())
            if referrer_id:
                safe_create_task(invalidate_user_cache(referrer_id))

            return True, "success"

        except IntegrityError:
            s.rollback()
            return False, "already_processed"

        except Exception as e:
            s.rollback()
            log_audit(
                "payment_failed",
                level="WARNING",
                user_id=user_id,
                resource_type="Payment",
                details=f"provider={provider}, amount={amount}, error={e}",
            )
            return False, "payment_error"


def _admin_balance_change(telegram_id: int, amount: int) -> tuple[bool, str]:
    """
    Atomic admin balance change (top-up or deduction) with operation record.
    amount > 0 for top-up, amount < 0 for deduction.
    Returns (success, message).
    Raises ValueError if insufficient funds for deduction.
    """
    with Database().session() as s:
        try:
            s.begin()

            user = s.query(User).filter(
                User.telegram_id == telegram_id
            ).with_for_update().one_or_none()

            if not user:
                s.rollback()
                return False, "user_not_found"

            if amount < 0 and user.balance < abs(amount):
                s.rollback()
                raise ValueError("insufficient_funds")

            user.balance += amount

            operation = Operations(
                user_id=telegram_id,
                operation_value=amount,
                operation_time=datetime.now(timezone.utc)
            )
            s.add(operation)

            s.commit()

            safe_create_task(invalidate_user_cache(telegram_id))
            safe_create_task(invalidate_stats_cache())

            return True, "success"

        except ValueError:
            raise

        except Exception as e:
            s.rollback()
            log_audit(
                "admin_balance_change_failed",
                level="WARNING",
                user_id=telegram_id,
                resource_type="User",
                details=f"amount={amount}, error={e}",
            )
            return False, "balance_change_error"


# Async public API
buy_item_transaction = run_sync(_buy_item_transaction)
process_payment_with_referral = run_sync(_process_payment_with_referral)
admin_balance_change = run_sync(_admin_balance_change)
