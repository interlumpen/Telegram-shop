from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import select

from bot.misc.services.cleanup import CleanupManager
from bot.misc.services.recovery import RecoveryManager
from bot.database.methods.create import create_pending_payment
from bot.database.main import Database
from bot.database.models.main import Payments


class TestRecoveryManager:

    def setup_method(self):
        self.bot = AsyncMock()
        self.bot.get_me = AsyncMock(return_value=MagicMock(username="test_bot"))
        self.manager = RecoveryManager(self.bot)

    async def test_check_and_process_paid_payment(self, user_factory):
        await user_factory(telegram_id=500001, balance=0)
        await create_pending_payment("cryptopay", "rec_inv_1", 500001, 200, "RUB")

        # Get the payment object
        async with Database().session() as s:
            payment = (await s.execute(select(Payments).filter(
                Payments.external_id == "rec_inv_1"
            ))).scalars().first()
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
        async with Database().session() as s:
            p = (await s.execute(select(Payments).filter(Payments.external_id == "rec_inv_1"))).scalars().first()
            assert p.status == "succeeded"

    async def test_check_and_process_expired_payment(self, user_factory):
        await user_factory(telegram_id=500002)
        await create_pending_payment("cryptopay", "rec_inv_2", 500002, 100, "RUB")

        async with Database().session() as s:
            payment = (await s.execute(select(Payments).filter(
                Payments.external_id == "rec_inv_2"
            ))).scalars().first()
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
        async with Database().session() as s:
            p = (await s.execute(select(Payments).filter(Payments.external_id == "rec_inv_2"))).scalars().first()
            assert p.status == "failed"

    async def test_health_check_does_not_call_telegram(self, fake_cache):
        """The per-minute health check must not spend a Telegram API call —
        polling already proves connectivity."""
        await self.manager.periodic_health_check()

        self.bot.get_me.assert_not_awaited()
        assert fake_cache.store.get("health:check") == "ok"

    async def test_start_creates_tasks(self):
        # Patch the recovery methods to not actually run
        self.manager.recover_pending_payments = AsyncMock()
        self.manager.periodic_health_check = AsyncMock()

        await self.manager.start()
        assert self.manager.running is True
        assert len(self.manager.recovery_tasks) == 2

        await self.manager.stop()
        assert self.manager.running is False

    async def test_run_periodically_survives_a_crash(self):
        """A failing pass must back off and be retried, not kill the task."""
        self.manager.running = True
        call_count = 0

        async def flaky():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("test error")
            # Second iteration: stop the loop so the test terminates.
            self.manager.running = False

        # Patch the sleeps so neither the backoff nor the interval really waits.
        with patch("bot.misc.services.recovery.asyncio.sleep", new=AsyncMock()) as mock_sleep:
            await self.manager._run_periodically(flaky, interval=300)

        assert call_count == 2  # crashed once, then retried
        # Backoff after the crash, then the normal interval after the good pass.
        assert [c.args[0] for c in mock_sleep.await_args_list] == [
            self.manager.ERROR_BACKOFF, 300,
        ]

    async def test_check_and_process_api_timeout(self, user_factory):
        """API timeout should not crash the recovery manager."""
        await user_factory(telegram_id=500003, balance=0)
        await create_pending_payment("cryptopay", "rec_inv_timeout", 500003, 300, "RUB")

        async with Database().session() as s:
            payment = (await s.execute(select(Payments).filter(
                Payments.external_id == "rec_inv_timeout"
            ))).scalars().first()
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
        async with Database().session() as s:
            p = (await s.execute(select(Payments).filter(Payments.external_id == "rec_inv_timeout"))).scalars().first()
            assert p.status == "pending"

    async def test_check_and_process_active_payment_no_change(self, user_factory):
        """Active (not yet paid/expired) payment should stay pending."""
        await user_factory(telegram_id=500004, balance=0)
        await create_pending_payment("cryptopay", "rec_inv_active", 500004, 150, "RUB")

        async with Database().session() as s:
            payment = (await s.execute(select(Payments).filter(
                Payments.external_id == "rec_inv_active"
            ))).scalars().first()
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

        async with Database().session() as s:
            p = (await s.execute(select(Payments).filter(Payments.external_id == "rec_inv_active"))).scalars().first()
            assert p.status == "pending"

    async def test_check_non_cryptopay_provider_skipped(self, user_factory):
        """Non-cryptopay payments should be skipped."""
        await user_factory(telegram_id=500005, balance=0)
        await create_pending_payment("stars", "stars_ext_1", 500005, 100, "XTR")

        async with Database().session() as s:
            payment = (await s.execute(select(Payments).filter(
                Payments.external_id == "stars_ext_1"
            ))).scalars().first()
            payment_copy = MagicMock()
            payment_copy.id = payment.id
            payment_copy.provider = payment.provider
            payment_copy.external_id = payment.external_id
            payment_copy.user_id = payment.user_id
            payment_copy.amount = payment.amount
            payment_copy.currency = payment.currency

        # Should not attempt API call for non-cryptopay
        await self.manager._check_and_process_payment(payment_copy)

        async with Database().session() as s:
            p = (await s.execute(select(Payments).filter(Payments.external_id == "stars_ext_1"))).scalars().first()
            assert p.status == "pending"


class TestCleanupRetention:
    def setup_method(self):
        self.manager = CleanupManager()

    async def _run_one_sweep(self, monkeypatch, *, audit_days, payments_days):
        from bot.misc.env import EnvKeys
        monkeypatch.setattr(EnvKeys, "AUDIT_RETENTION_DAYS", audit_days, raising=False)
        monkeypatch.setattr(EnvKeys, "PAYMENTS_RETENTION_DAYS", payments_days, raising=False)

        self.manager.running = True

        async def stop_before_working(_delay):
            # daily_cleanup sleeps until 04:00 UTC first; skip the wait, then
            # end the loop after this single pass.
            self.manager.running = False

        with patch("bot.misc.services.cleanup.asyncio.sleep", side_effect=stop_before_working):
            await self.manager.daily_cleanup()

    async def _seed(self):
        from datetime import datetime, timedelta, timezone
        from bot.database.models.main import AuditLog, Payments as P
        old = datetime.now(timezone.utc) - timedelta(days=365)
        async with Database().session() as s:
            s.add(AuditLog(timestamp=old, level="INFO", action="ancient"))
            s.add(P(provider="cryptopay", external_id="ret_old", user_id=None,
                    amount=10, currency="RUB", status="pending", created_at=old))

    async def _counts(self):
        from sqlalchemy import func
        from bot.database.models.main import AuditLog, Payments as P
        async with Database().session() as s:
            audit = (await s.execute(select(func.count(AuditLog.id)))).scalar()
            payments = (await s.execute(select(func.count(P.id)))).scalar()
        return audit, payments

    async def test_zero_retention_deletes_nothing(self, monkeypatch):
        await self._seed()
        before = await self._counts()

        await self._run_one_sweep(monkeypatch, audit_days=0, payments_days=0)

        # The sweep logs its own audit row, so audit can only have grown.
        audit_after, payments_after = await self._counts()
        assert audit_after >= before[0]
        assert payments_after == before[1]

    async def test_positive_retention_still_prunes(self, monkeypatch):
        await self._seed()

        await self._run_one_sweep(monkeypatch, audit_days=90, payments_days=90)

        from bot.database.models.main import Payments as P
        async with Database().session() as s:
            stale = (await s.execute(
                select(P).where(P.external_id == "ret_old")
            )).scalars().first()
        assert stale is None
