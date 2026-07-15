import pytest
from decimal import Decimal
from unittest.mock import patch, AsyncMock, MagicMock

from sqlalchemy import select

from bot.database.methods.read import check_user
from bot.database.main import Database
from bot.database.models.main import Payments


class TestReplenishBalance:

    async def test_no_payment_methods_enabled(self, make_callback_query, fsm_context):
        from bot.handlers.user.balance_and_payment import replenish_balance_callback_handler

        call = make_callback_query(data="replenish_balance", user_id=400001)

        with patch('bot.handlers.user.balance_and_payment._any_payment_method_enabled', return_value=False):
            await replenish_balance_callback_handler(call, fsm_context)

        call.answer.assert_called_once()

    async def test_sets_waiting_amount_state(self, make_callback_query, fsm_context):
        from bot.handlers.user.balance_and_payment import replenish_balance_callback_handler
        from bot.states import BalanceStates

        call = make_callback_query(data="replenish_balance", user_id=400002)

        with patch('bot.handlers.user.balance_and_payment._any_payment_method_enabled', return_value=True), \
             patch('bot.handlers.user.balance_and_payment.EnvKeys') as env:
            env.PAY_CURRENCY = "RUB"
            await replenish_balance_callback_handler(call, fsm_context)

        state = await fsm_context.get_state()
        assert state == BalanceStates.waiting_amount


class TestCheckingPayment:

    async def test_no_active_invoice(self, make_callback_query, fsm_context):
        from bot.handlers.user.balance_and_payment import checking_payment

        call = make_callback_query(data="check", user_id=400010)
        # Empty state - no payment_type
        await fsm_context.clear()

        await checking_payment(call, fsm_context)

        call.answer.assert_called_once()

    async def test_cryptopay_paid_credits_balance(self, make_callback_query, fsm_context, user_factory):
        from bot.handlers.user.balance_and_payment import checking_payment

        await user_factory(telegram_id=400011, balance=0)

        call = make_callback_query(data="check", user_id=400011)

        await fsm_context.update_data(
            payment_type="cryptopay",
            invoice_id="inv_123",
        )

        mock_crypto = AsyncMock()
        mock_crypto.get_invoice = AsyncMock(return_value={
            "status": "paid",
            "amount": "100.00",
        })

        with patch('bot.handlers.user.balance_and_payment.CryptoPayAPI', return_value=mock_crypto), \
             patch('bot.handlers.user.balance_and_payment.EnvKeys') as env:
            env.REFERRAL_PERCENT = 0
            env.PAY_CURRENCY = "RUB"
            await checking_payment(call, fsm_context)

        # Balance should be updated in DB
        user = await check_user(400011)
        assert user['balance'] == Decimal("100")

        # Payment record should exist
        async with Database().session() as s:
            result = await s.execute(
                select(Payments).where(Payments.external_id == "inv_123")
            )
            payment = result.scalars().first()
            assert payment is not None
            assert payment.status == "succeeded"

    async def test_cryptopay_not_paid_yet(self, make_callback_query, fsm_context, user_factory):
        from bot.handlers.user.balance_and_payment import checking_payment

        await user_factory(telegram_id=400012)

        call = make_callback_query(data="check", user_id=400012)
        await fsm_context.update_data(payment_type="cryptopay", invoice_id="inv_456")

        mock_crypto = AsyncMock()
        mock_crypto.get_invoice = AsyncMock(return_value={"status": "active"})

        with patch('bot.handlers.user.balance_and_payment.CryptoPayAPI', return_value=mock_crypto):
            await checking_payment(call, fsm_context)

        call.answer.assert_called()
        # Balance should still be 0
        user = await check_user(400012)
        assert user['balance'] == Decimal("0")

    async def test_cryptopay_expired(self, make_callback_query, fsm_context, user_factory):
        from bot.handlers.user.balance_and_payment import checking_payment

        await user_factory(telegram_id=400013)

        call = make_callback_query(data="check", user_id=400013)
        await fsm_context.update_data(payment_type="cryptopay", invoice_id="inv_789")

        mock_crypto = AsyncMock()
        mock_crypto.get_invoice = AsyncMock(return_value={"status": "expired"})

        with patch('bot.handlers.user.balance_and_payment.CryptoPayAPI', return_value=mock_crypto):
            await checking_payment(call, fsm_context)

        call.answer.assert_called()

    async def test_cryptopay_already_processed(self, make_callback_query, fsm_context, user_factory):
        from bot.handlers.user.balance_and_payment import checking_payment

        await user_factory(telegram_id=400014, balance=0)

        # First payment
        call1 = make_callback_query(data="check", user_id=400014)
        await fsm_context.update_data(payment_type="cryptopay", invoice_id="inv_dup")

        mock_crypto = AsyncMock()
        mock_crypto.get_invoice = AsyncMock(return_value={
            "status": "paid", "amount": "50.00"
        })

        with patch('bot.handlers.user.balance_and_payment.CryptoPayAPI', return_value=mock_crypto), \
             patch('bot.handlers.user.balance_and_payment.EnvKeys') as env:
            env.REFERRAL_PERCENT = 0
            env.PAY_CURRENCY = "RUB"
            await checking_payment(call1, fsm_context)

        # Second attempt with same invoice
        call2 = make_callback_query(data="check", user_id=400014)
        await fsm_context.update_data(payment_type="cryptopay", invoice_id="inv_dup")

        with patch('bot.handlers.user.balance_and_payment.CryptoPayAPI', return_value=mock_crypto), \
             patch('bot.handlers.user.balance_and_payment.EnvKeys') as env:
            env.REFERRAL_PERCENT = 0
            env.PAY_CURRENCY = "RUB"
            await checking_payment(call2, fsm_context)

        # Balance should only be credited once
        user = await check_user(400014)
        assert user['balance'] == Decimal("50")


class TestCryptoPayFractionalAmounts:
    """Balance is NUMERIC(12,2): the kopecks of an invoice must survive."""

    async def test_fractional_amount_is_credited_in_full(self, make_callback_query,
                                                         fsm_context, user_factory):
        from bot.handlers.user.balance_and_payment import checking_payment

        await user_factory(telegram_id=400030, balance=0)
        call = make_callback_query(data="check", user_id=400030)
        await fsm_context.update_data(payment_type="cryptopay", invoice_id="inv_frac")

        mock_crypto = AsyncMock()
        mock_crypto.get_invoice = AsyncMock(return_value={"status": "paid", "amount": "20.50"})

        with patch('bot.handlers.user.balance_and_payment.CryptoPayAPI', return_value=mock_crypto), \
             patch('bot.handlers.user.balance_and_payment.EnvKeys') as env:
            env.REFERRAL_PERCENT = 0
            env.PAY_CURRENCY = "RUB"
            await checking_payment(call, fsm_context)

        # Was truncated to 20 before: quantize(Decimal("1.")) ate the .50
        user = await check_user(400030)
        assert user['balance'] == Decimal("20.50")

        async with Database().session() as s:
            payment = (await s.execute(
                select(Payments).where(Payments.external_id == "inv_frac")
            )).scalars().first()
            assert payment.amount == Decimal("20.50")   # ledger agrees with the credit

    async def test_zero_amount_is_rejected(self, make_callback_query, fsm_context, user_factory):
        from bot.handlers.user.balance_and_payment import checking_payment

        await user_factory(telegram_id=400031, balance=0)
        call = make_callback_query(data="check", user_id=400031)
        await fsm_context.update_data(payment_type="cryptopay", invoice_id="inv_zero")

        mock_crypto = AsyncMock()
        mock_crypto.get_invoice = AsyncMock(return_value={"status": "paid", "amount": "0"})

        with patch('bot.handlers.user.balance_and_payment.CryptoPayAPI', return_value=mock_crypto), \
             patch('bot.handlers.user.balance_and_payment.EnvKeys') as env:
            env.REFERRAL_PERCENT = 0
            env.PAY_CURRENCY = "RUB"
            await checking_payment(call, fsm_context)

        user = await check_user(400031)
        assert user['balance'] == Decimal("0")


class TestSuccessfulPaymentIdempotency:

    def _make_successful_payment(self, charge_id=None):
        sp = MagicMock()
        sp.currency = "XTR"
        sp.total_amount = 100
        sp.invoice_payload = '{"amount": 100}'
        sp.telegram_payment_charge_id = charge_id
        sp.provider_payment_charge_id = None
        return sp

    async def test_replay_without_charge_id_credits_once(self, make_message, user_factory):
        """A missing charge id must still yield a stable idempotency key.

        The old uuid4() fallback made every replay look like a new payment,
        defeating uq_payment_provider_ext entirely.
        """
        from bot.handlers.user.balance_and_payment import successful_payment_handler

        await user_factory(telegram_id=400040, balance=0)

        with patch('bot.handlers.user.balance_and_payment.EnvKeys') as env:
            env.REFERRAL_PERCENT = 0
            env.PAY_CURRENCY = "RUB"
            env.STARS_PER_VALUE = 1

            first = make_message(text="", user_id=400040)
            first.successful_payment = self._make_successful_payment()
            await successful_payment_handler(first)

            second = make_message(text="", user_id=400040)
            second.successful_payment = self._make_successful_payment()
            await successful_payment_handler(second)

        user = await check_user(400040)
        assert user['balance'] == Decimal("100")   # not 200

        async with Database().session() as s:
            payments = (await s.execute(
                select(Payments).where(Payments.user_id == 400040)
            )).scalars().all()
            assert len(payments) == 1

    async def test_fallback_key_is_deterministic(self, make_message, user_factory):
        from bot.handlers.user.balance_and_payment import successful_payment_handler

        await user_factory(telegram_id=400041, balance=0)

        with patch('bot.handlers.user.balance_and_payment.EnvKeys') as env:
            env.REFERRAL_PERCENT = 0
            env.PAY_CURRENCY = "RUB"
            env.STARS_PER_VALUE = 1

            message = make_message(text="", user_id=400041)
            message.successful_payment = self._make_successful_payment()
            await successful_payment_handler(message)

        async with Database().session() as s:
            payment = (await s.execute(
                select(Payments).where(Payments.user_id == 400041)
            )).scalars().one()
            assert payment.external_id.startswith("stars:fallback:")

    async def test_charge_id_is_used_when_present(self, make_message, user_factory):
        from bot.handlers.user.balance_and_payment import successful_payment_handler

        await user_factory(telegram_id=400042, balance=0)

        with patch('bot.handlers.user.balance_and_payment.EnvKeys') as env:
            env.REFERRAL_PERCENT = 0
            env.PAY_CURRENCY = "RUB"
            env.STARS_PER_VALUE = 1

            message = make_message(text="", user_id=400042)
            message.successful_payment = self._make_successful_payment(charge_id="tg_charge_1")
            await successful_payment_handler(message)

        async with Database().session() as s:
            payment = (await s.execute(
                select(Payments).where(Payments.user_id == 400042)
            )).scalars().one()
            assert payment.external_id == "tg_charge_1"


class TestBuyItemHandler:

    async def test_buy_item_success(self, make_callback_query, fsm_context, user_factory, item_factory):
        from bot.handlers.user.balance_and_payment import buy_item_callback_handler

        await user_factory(telegram_id=400020, balance=500)
        await item_factory(name="TestWidget", price=100, values=[("widget_value_1", False)])

        call = make_callback_query(data="buy_item", user_id=400020)
        await fsm_context.update_data(csrf_item="TestWidget")

        with patch('bot.handlers.user.balance_and_payment.EnvKeys') as env:
            env.PAY_CURRENCY = "RUB"
            await buy_item_callback_handler(call, fsm_context)

        user = await check_user(400020)
        assert user['balance'] == Decimal("400")

    async def test_buy_item_insufficient_funds(self, make_callback_query, fsm_context, user_factory, item_factory):
        from bot.handlers.user.balance_and_payment import buy_item_callback_handler

        await user_factory(telegram_id=400021, balance=10)
        await item_factory(name="ExpensiveItem", price=1000, values=[("val", False)])

        call = make_callback_query(data="buy_item", user_id=400021)
        await fsm_context.update_data(csrf_item="ExpensiveItem")

        with patch('bot.handlers.user.balance_and_payment.EnvKeys') as env:
            env.PAY_CURRENCY = "RUB"
            await buy_item_callback_handler(call, fsm_context)

        # Balance should be unchanged
        user = await check_user(400021)
        assert user['balance'] == Decimal("10")

    async def test_buy_item_no_csrf_item(self, make_callback_query, fsm_context, user_factory):
        from bot.handlers.user.balance_and_payment import buy_item_callback_handler

        await user_factory(telegram_id=400022)

        call = make_callback_query(data="buy_item", user_id=400022)
        # No csrf_item in state

        await buy_item_callback_handler(call, fsm_context)

        call.answer.assert_called()
