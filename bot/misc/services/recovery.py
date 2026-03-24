import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update, text

logger = logging.getLogger(__name__)


class RecoveryManager:
    """Disaster Recovery Manager — payment recovery and health monitoring"""

    def __init__(self, bot):
        self.bot = bot
        self.recovery_tasks = []
        self.running = False

    async def start(self):
        """Starting the recovery system"""
        logger.info("Starting recovery manager...")
        self.running = True

        self.recovery_tasks.append(
            asyncio.create_task(self._safe_run(self.recover_pending_payments))
        )

        self.recovery_tasks.append(
            asyncio.create_task(self._safe_run(self.periodic_health_check))
        )

    async def stop(self):
        """Stopping the recovery system"""
        self.running = False
        for task in self.recovery_tasks:
            task.cancel()
        await asyncio.gather(*self.recovery_tasks, return_exceptions=True)
        logger.info("Recovery manager stopped")

    async def _safe_run(self, coro_func, *args):
        """Safe startup with automatic restart on failure"""
        while self.running:
            try:
                await coro_func(*args)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Recovery task error: {e}", exc_info=True)
                await asyncio.sleep(30)

    async def recover_pending_payments(self):
        """Recovery of suspended payments"""
        from bot.database import Database
        from bot.database.models import Payments

        while self.running:
            try:
                payment_copies = []
                async with Database().session() as s:
                    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
                    result = await s.execute(
                        select(Payments).where(
                            Payments.status == "pending",
                            Payments.created_at < cutoff,
                            Payments.provider == "cryptopay"
                        )
                    )
                    pending_payments = result.scalars().all()

                    for p in pending_payments:
                        payment_copies.append({
                            'id': p.id,
                            'provider': p.provider,
                            'external_id': p.external_id,
                            'user_id': p.user_id,
                            'amount': p.amount,
                            'currency': p.currency,
                        })

                for pc in payment_copies:
                    await self._check_and_process_payment(pc)

            except Exception as e:
                logger.error(f"Error recovering payments: {e}")

            await asyncio.sleep(300)

    async def _check_and_process_payment(self, payment):
        """Verification and processing of a specific payment.

        Args:
            payment: dict with keys id, provider, external_id, user_id, amount, currency
        """
        from bot.database.methods.transactions import process_payment_with_referral
        from bot.misc import EnvKeys
        from bot.misc.services.payment import CryptoPayAPI
        from bot.i18n import localize

        p_id = payment['id'] if isinstance(payment, dict) else payment.id
        p_provider = payment['provider'] if isinstance(payment, dict) else payment.provider
        p_external_id = payment['external_id'] if isinstance(payment, dict) else payment.external_id
        p_user_id = payment['user_id'] if isinstance(payment, dict) else payment.user_id
        p_amount = payment['amount'] if isinstance(payment, dict) else payment.amount
        p_currency = payment['currency'] if isinstance(payment, dict) else payment.currency

        try:
            if p_provider == "cryptopay" and EnvKeys.CRYPTO_PAY_TOKEN:
                crypto = CryptoPayAPI()
                info = await crypto.get_invoice(p_external_id)

                if info.get("status") == "paid":
                    success, _ = await process_payment_with_referral(
                        user_id=p_user_id,
                        amount=p_amount,
                        provider=p_provider,
                        external_id=p_external_id,
                        referral_percent=EnvKeys.REFERRAL_PERCENT
                    )

                    if success:
                        logger.info(f"Recovered payment {p_external_id}")
                        try:
                            await self.bot.send_message(
                                p_user_id,
                                localize("payments.topped_simple", amount=p_amount, currency=p_currency)
                            )
                        except Exception as e:
                            logger.error(f"Failed to notify user {p_user_id}: {e}")

                elif info.get("status") in ["expired", "failed"]:
                    await self._mark_payment_failed(p_id)

        except Exception as e:
            logger.error(f"Error processing payment {p_id}: {e}")

    async def _mark_payment_failed(self, payment_id: int):
        """Mark payment as failed."""
        from bot.database import Database
        from bot.database.models import Payments

        async with Database().session() as s:
            await s.execute(
                update(Payments).where(Payments.id == payment_id).values(status="failed")
            )

    async def periodic_health_check(self):
        """Periodic system health checks"""
        from bot.database import Database

        while self.running:
            try:
                async with Database().session() as s:
                    await s.execute(text("SELECT 1"))

                from bot.misc.caching.cache import get_cache_manager
                cache = get_cache_manager()
                if cache:
                    await cache.check_health()
                    await cache.set("health:check", "ok", ttl=60)

                me = await self.bot.get_me()

                logger.debug(f"Health check passed: Bot @{me.username} is alive")

            except Exception as e:
                logger.error(f"Health check failed: {e}")

            await asyncio.sleep(60)
