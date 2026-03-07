import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.misc.services.recovery import RecoveryManager
from bot.database.methods.create import _create_pending_payment as create_pending_payment
from bot.database.main import Database
from bot.database.models.main import Payments


class TestRecoveryManager:

    def setup_method(self):
        self.bot = AsyncMock()
        self.bot.get_me = AsyncMock(return_value=MagicMock(username="test_bot"))
        self.manager = RecoveryManager(self.bot)

    @pytest.mark.asyncio
    async def test_check_and_process_paid_payment(self, user_factory):
        user_factory(telegram_id=500001, balance=0)
        create_pending_payment("cryptopay", "rec_inv_1", 500001, 200, "RUB")

        # Get the payment object
        with Database().session() as s:
            payment = s.query(Payments).filter(
                Payments.external_id == "rec_inv_1"
            ).first()
            payment_copy = MagicMock()
            payment_copy.id = payment.id
            payment_copy.provider = payment.provider
            payment_copy.external_id = payment.external_id
            payment_copy.user_id = payment.user_id
            payment_copy.amount = payment.amount
            payment_copy.currency = payment.currency

        mock_crypto = AsyncMock()
        mock_crypto.get_invoice = AsyncMock(return_value={"status": "paid"})

        with patch('bot.misc.services.payment.CryptoPayAPI', return_value=mock_crypto):
            await self.manager._check_and_process_payment(payment_copy)

        # Verify payment processed
        with Database().session() as s:
            p = s.query(Payments).filter(Payments.external_id == "rec_inv_1").first()
            assert p.status == "succeeded"

    @pytest.mark.asyncio
    async def test_check_and_process_expired_payment(self, user_factory):
        user_factory(telegram_id=500002)
        create_pending_payment("cryptopay", "rec_inv_2", 500002, 100, "RUB")

        with Database().session() as s:
            payment = s.query(Payments).filter(
                Payments.external_id == "rec_inv_2"
            ).first()
            payment_copy = MagicMock()
            payment_copy.id = payment.id
            payment_copy.provider = payment.provider
            payment_copy.external_id = payment.external_id
            payment_copy.user_id = payment.user_id
            payment_copy.amount = payment.amount
            payment_copy.currency = payment.currency

        mock_crypto = AsyncMock()
        mock_crypto.get_invoice = AsyncMock(return_value={"status": "expired"})

        with patch('bot.misc.services.payment.CryptoPayAPI', return_value=mock_crypto):
            await self.manager._check_and_process_payment(payment_copy)

        # Should be marked as failed
        with Database().session() as s:
            p = s.query(Payments).filter(Payments.external_id == "rec_inv_2").first()
            assert p.status == "failed"

    @pytest.mark.asyncio
    async def test_start_creates_tasks(self):
        # Patch the recovery methods to not actually run
        self.manager.recover_pending_payments = AsyncMock()
        self.manager.periodic_health_check = AsyncMock()

        await self.manager.start()
        assert self.manager.running is True
        assert len(self.manager.recovery_tasks) == 2

        await self.manager.stop()
        assert self.manager.running is False

    @pytest.mark.asyncio
    async def test_safe_run_handles_exceptions(self):
        async def failing_coro():
            raise ValueError("test error")

        # Should not raise
        await self.manager._safe_run(failing_coro())

    @pytest.mark.asyncio
    async def test_check_and_process_api_timeout(self, user_factory):
        """API timeout should not crash the recovery manager."""
        user_factory(telegram_id=500003, balance=0)
        create_pending_payment("cryptopay", "rec_inv_timeout", 500003, 300, "RUB")

        with Database().session() as s:
            payment = s.query(Payments).filter(
                Payments.external_id == "rec_inv_timeout"
            ).first()
            payment_copy = MagicMock()
            payment_copy.id = payment.id
            payment_copy.provider = payment.provider
            payment_copy.external_id = payment.external_id
            payment_copy.user_id = payment.user_id
            payment_copy.amount = payment.amount
            payment_copy.currency = payment.currency

        mock_crypto = AsyncMock()
        mock_crypto.get_invoice = AsyncMock(side_effect=Exception("Connection timeout"))

        with patch('bot.misc.services.payment.CryptoPayAPI', return_value=mock_crypto):
            # Should not raise
            await self.manager._check_and_process_payment(payment_copy)

        # Payment status should remain unchanged (pending)
        with Database().session() as s:
            p = s.query(Payments).filter(Payments.external_id == "rec_inv_timeout").first()
            assert p.status == "pending"

    @pytest.mark.asyncio
    async def test_check_and_process_active_payment_no_change(self, user_factory):
        """Active (not yet paid/expired) payment should stay pending."""
        user_factory(telegram_id=500004, balance=0)
        create_pending_payment("cryptopay", "rec_inv_active", 500004, 150, "RUB")

        with Database().session() as s:
            payment = s.query(Payments).filter(
                Payments.external_id == "rec_inv_active"
            ).first()
            payment_copy = MagicMock()
            payment_copy.id = payment.id
            payment_copy.provider = payment.provider
            payment_copy.external_id = payment.external_id
            payment_copy.user_id = payment.user_id
            payment_copy.amount = payment.amount
            payment_copy.currency = payment.currency

        mock_crypto = AsyncMock()
        mock_crypto.get_invoice = AsyncMock(return_value={"status": "active"})

        with patch('bot.misc.services.payment.CryptoPayAPI', return_value=mock_crypto):
            await self.manager._check_and_process_payment(payment_copy)

        with Database().session() as s:
            p = s.query(Payments).filter(Payments.external_id == "rec_inv_active").first()
            assert p.status == "pending"

    @pytest.mark.asyncio
    async def test_check_non_cryptopay_provider_skipped(self, user_factory):
        """Non-cryptopay payments should be skipped."""
        user_factory(telegram_id=500005, balance=0)
        create_pending_payment("stars", "stars_ext_1", 500005, 100, "XTR")

        with Database().session() as s:
            payment = s.query(Payments).filter(
                Payments.external_id == "stars_ext_1"
            ).first()
            payment_copy = MagicMock()
            payment_copy.id = payment.id
            payment_copy.provider = payment.provider
            payment_copy.external_id = payment.external_id
            payment_copy.user_id = payment.user_id
            payment_copy.amount = payment.amount
            payment_copy.currency = payment.currency

        # Should not attempt API call for non-cryptopay
        await self.manager._check_and_process_payment(payment_copy)

        with Database().session() as s:
            p = s.query(Payments).filter(Payments.external_id == "stars_ext_1").first()
            assert p.status == "pending"
