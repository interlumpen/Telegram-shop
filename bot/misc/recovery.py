import asyncio
import logging
from datetime import datetime, timedelta
from pathlib import Path

from bot.database import Database
from bot.database.models import Payments
from bot.i18n import localize
from bot.misc.payment import CryptoPayAPI
from bot.misc import EnvKeys
from bot.misc.cache import get_cache_manager
from bot.database.methods.transactions import process_payment_with_referral

logger = logging.getLogger(__name__)


class RecoveryManager:
    """Disaster Recovery Manager"""

    def __init__(self, bot):
        self.bot = bot
        self.recovery_tasks = []
        self.running = False

    async def start(self):
        """Starting the recovery system"""
        logger.info("Starting recovery manager...")
        self.running = True

        # Recovery of pending payments
        self.recovery_tasks.append(
            asyncio.create_task(self._safe_run(self.recover_pending_payments()))
        )

        # Restore interrupted mailings
        self.recovery_tasks.append(
            asyncio.create_task(self._safe_run(self.recover_interrupted_broadcasts()))
        )

        # Periodic status checks
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
        while self.running:
            try:
                with Database().session() as s:
                    # Find payments older than 1 hour in pending status
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

            # Wait 5 minutes before the next check
            await asyncio.sleep(300)

    async def _check_and_process_payment(self, payment: Payments):
        """Verification and processing of a specific payment"""
        try:
            if payment.provider == "cryptopay" and EnvKeys.CRYPTO_PAY_TOKEN:
                crypto = CryptoPayAPI()
                info = await crypto.get_invoice(payment.external_id)

                if info.get("status") == "paid":
                    # Process payment
                    success, _ = process_payment_with_referral(
                        user_id=payment.user_id,
                        amount=payment.amount,
                        provider=payment.provider,
                        external_id=payment.external_id,
                        referral_percent=EnvKeys.REFERRAL_PERCENT
                    )

                    if success:
                        logger.info(f"Recovered payment {payment.external_id}")
                        # Notify user
                        try:
                            await self.bot.send_message(
                                payment.user_id,
                                localize("payments.topped_simple", amount=payment.amount, currency=payment.currency)
                            )
                        except Exception as e:
                            logger.error(f"Failed to notify user {payment.user_id}: {e}")

                elif info.get("status") in ["expired", "failed"]:
                    # Mark as unsuccessful
                    with Database().session() as s:
                        s.query(Payments).filter(
                            Payments.id == payment.id
                        ).update({"status": "failed"})

        except Exception as e:
            logger.error(f"Error processing payment {payment.id}: {e}")

    async def recover_interrupted_broadcasts(self):
        """Restore interrupted mailings"""
        # Loading state from Redis at startup
        try:
            from bot.misc.cache import get_cache_manager

            cache = get_cache_manager()
            if cache:
                broadcast_state = await cache.get("broadcast:interrupted")
                if broadcast_state:
                    logger.info(f"Found interrupted broadcast: {broadcast_state}")
                    # Continue mailing from where left off
                    await self._resume_broadcast(broadcast_state)
        except Exception as e:
            logger.error(f"Error recovering broadcasts: {e}")

    async def _resume_broadcast(self, state: dict):
        """Resuming an interrupted mailing"""
        logger.info("Broadcast resumption not implemented yet")

    async def periodic_health_check(self):
        """Periodic system health checks"""
        while self.running:
            try:
                # Check connections to database
                with Database().session() as s:
                    from sqlalchemy import text
                    s.execute(text("SELECT 1"))

                # Checking Redis
                from bot.misc.cache import get_cache_manager
                cache = get_cache_manager()
                if cache:
                    await cache.set("health:check", "ok", ttl=60)

                # Telegram API check
                me = await self.bot.get_me()

                logger.debug(f"Health check passed: Bot @{me.username} is alive")

            except Exception as e:
                logger.error(f"Health check failed: {e}")

            # Wait 60 seconds before the next test
            await asyncio.sleep(60)


class StateManager:
    """Save state manager for recovery"""

    def __init__(self):
        self.state_file = "data/bot_state.json"

    async def save_broadcast_state(self, user_ids: list, sent_count: int,
                                   message_text: str, start_time: datetime):
        """Saving the mailing status"""
        import json
        from pathlib import Path

        Path("data").mkdir(exist_ok=True)

        state = {
            "user_ids": user_ids,
            "sent_count": sent_count,
            "message_text": message_text,
            "start_time": start_time.isoformat(),
            "timestamp": datetime.now().isoformat()
        }

        try:
            with open(self.state_file, 'w') as f:
                json.dump(state, f)

            # Also save in Redis for quick access
            from bot.misc.cache import get_cache_manager
            cache = get_cache_manager()
            if cache:
                await cache.set("broadcast:state", state, ttl=3600)
        except Exception as e:
            logger.error(f"Failed to save broadcast state: {e}")
