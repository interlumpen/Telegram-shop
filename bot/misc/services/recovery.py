import asyncio
import logging
from datetime import datetime, timedelta

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
            asyncio.create_task(self._safe_run(self.recover_pending_payments()))
        )

        self.recovery_tasks.append(
            asyncio.create_task(self._safe_run(self.periodic_health_check()))
        )

    async def stop(self):
        """Stopping the recovery system"""
        self.running = False
        for task in self.recovery_tasks:
            task.cancel()
        await asyncio.gather(*self.recovery_tasks, return_exceptions=True)
        logger.info("Recovery manager stopped")

    async def _safe_run(self, coro):
        """Safe startup of coroutine with error handling"""
        try:
            await coro
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"Recovery task error: {e}", exc_info=True)

    async def recover_pending_payments(self):
        """Recovery of suspended payments"""
        from bot.database import Database
        from bot.database.models import Payments

        while self.running:
            try:
                with Database().session() as s:
                    cutoff = datetime.now() - timedelta(hours=1)
                    pending_payments = s.query(Payments).filter(
                        Payments.status == "pending",
                        Payments.created_at < cutoff,
                        Payments.provider == "cryptopay"
                    ).all()

                    for payment in pending_payments:
                        await self._check_and_process_payment(payment)

            except Exception as e:
                logger.error(f"Error recovering payments: {e}")

            await asyncio.sleep(300)

    async def _check_and_process_payment(self, payment):
        """Verification and processing of a specific payment"""
        from bot.database import Database
        from bot.database.models import Payments
        from bot.database.methods.transactions import process_payment_with_referral
        from bot.misc import EnvKeys
        from bot.misc.services.payment import CryptoPayAPI
        from bot.i18n import localize

        try:
            if payment.provider == "cryptopay" and EnvKeys.CRYPTO_PAY_TOKEN:
                crypto = CryptoPayAPI()
                info = await crypto.get_invoice(payment.external_id)

                if info.get("status") == "paid":
                    success, _ = process_payment_with_referral(
                        user_id=payment.user_id,
                        amount=payment.amount,
                        provider=payment.provider,
                        external_id=payment.external_id,
                        referral_percent=EnvKeys.REFERRAL_PERCENT
                    )

                    if success:
                        logger.info(f"Recovered payment {payment.external_id}")
                        try:
                            await self.bot.send_message(
                                payment.user_id,
                                localize("payments.topped_simple", amount=payment.amount, currency=payment.currency)
                            )
                        except Exception as e:
                            logger.error(f"Failed to notify user {payment.user_id}: {e}")

                elif info.get("status") in ["expired", "failed"]:
                    with Database().session() as s:
                        s.query(Payments).filter(
                            Payments.id == payment.id
                        ).update({"status": "failed"})

        except Exception as e:
            logger.error(f"Error processing payment {payment.id}: {e}")

    async def periodic_health_check(self):
        """Periodic system health checks"""
        from bot.database import Database

        while self.running:
            try:
                with Database().session() as s:
                    from sqlalchemy import text
                    s.execute(text("SELECT 1"))

                from bot.misc.caching.cache import get_cache_manager
                cache = get_cache_manager()
                if cache:
                    await cache.set("health:check", "ok", ttl=60)

                me = await self.bot.get_me()

                logger.debug(f"Health check passed: Bot @{me.username} is alive")

            except Exception as e:
                logger.error(f"Health check failed: {e}")

            await asyncio.sleep(60)
