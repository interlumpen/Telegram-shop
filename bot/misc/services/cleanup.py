import asyncio
import logging
from datetime import datetime, timedelta, timezone, time as dt_time

from sqlalchemy import delete

logger = logging.getLogger(__name__)


class CleanupManager:
    """Periodic cleanup of old audit_log entries and expired payments."""

    def __init__(self):
        self.tasks = []
        self.running = False

    async def start(self):
        logger.info("Starting cleanup manager...")
        self.running = True
        self.tasks.append(asyncio.create_task(self._safe_run(self.daily_cleanup)))

    async def stop(self):
        self.running = False
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        logger.info("Cleanup manager stopped")

    async def _safe_run(self, coro_func):
        while self.running:
            try:
                await coro_func()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Cleanup task error: {e}", exc_info=True)
                await asyncio.sleep(30)

    async def daily_cleanup(self):
        while self.running:
            # Wait until 4:00 UTC
            now = datetime.now(timezone.utc)
            target = datetime.combine(now.date(), dt_time(4, 0), tzinfo=timezone.utc)
            if now >= target:
                target += timedelta(days=1)
            wait_seconds = (target - now).total_seconds()
            await asyncio.sleep(wait_seconds)

            try:
                from bot.database import Database
                from bot.database.models.main import AuditLog, Payments
                from bot.misc.env import EnvKeys
                from bot.database.methods.audit import log_audit

                audit_days = EnvKeys.AUDIT_RETENTION_DAYS
                payments_days = EnvKeys.PAYMENTS_RETENTION_DAYS
                now = datetime.now(timezone.utc)

                audit_deleted = 0
                payments_deleted = 0

                async with Database().session() as s:
                    # 1. Delete old audit_log entries
                    if audit_days > 0:
                        audit_result = await s.execute(
                            delete(AuditLog).where(AuditLog.timestamp < now - timedelta(days=audit_days))
                        )
                        audit_deleted = audit_result.rowcount

                    # 2. Delete old pending/failed payments
                    if payments_days > 0:
                        payments_result = await s.execute(
                            delete(Payments).where(
                                Payments.status.in_(['pending', 'failed']),
                                Payments.created_at < now - timedelta(days=payments_days)
                            )
                        )
                        payments_deleted = payments_result.rowcount

                await log_audit(
                    "daily_cleanup",
                    details=f"audit_deleted={audit_deleted}, payments_deleted={payments_deleted}"
                )
                logger.info(f"Daily cleanup: audit={audit_deleted}, payments={payments_deleted}")

            except Exception as e:
                logger.error(f"Daily cleanup failed: {e}", exc_info=True)
