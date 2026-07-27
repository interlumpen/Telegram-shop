import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.main import Database
from bot.database.models.main import AuditLog
from bot.logger_mesh import audit_logger

_LOG_LEVELS = {
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
}


class AuditBuffer:
    """Collects audit rows and writes them out in batches.

    Buffering is only active while a flusher task is running: outside the bot
    process (tests, scripts) log_audit writes through immediately, so a caller
    that awaits it can still read the row back straight after.

    The file log is always written synchronously by log_audit, so a crash loses
    at most the DB copy of the last few seconds — never the audit trail itself.
    """

    MAX_BATCH = 50          # flush as soon as this many rows are waiting
    FLUSH_INTERVAL = 2.0    # ...or this long after the first one arrived
    MAX_BUFFERED = 10_000   # hard cap; beyond this rows are written through

    def __init__(self):
        self._rows: list[dict] = []
        self._wakeup = asyncio.Event()
        self._task: asyncio.Task | None = None

    @property
    def active(self) -> bool:
        return self._task is not None and not self._task.done()

    def add(self, row: dict) -> bool:
        """Queue a row. False if the caller should write it through itself."""
        if not self.active or len(self._rows) >= self.MAX_BUFFERED:
            return False
        self._rows.append(row)
        if len(self._rows) >= self.MAX_BATCH:
            self._wakeup.set()
        return True

    async def flush(self) -> int:
        """Write everything buffered so far. Returns the number of rows written."""
        if not self._rows:
            return 0
        batch, self._rows = self._rows, []
        try:
            async with Database().session() as s:
                await s.execute(insert(AuditLog), batch)
            return len(batch)
        except Exception:
            # The rows are already in the file log, so this is a degraded DB
            # copy rather than lost history. Dropping them keeps a persistent
            # DB failure from growing the buffer without bound.
            audit_logger.warning(
                "Failed to write %d buffered audit entries to DB", len(batch),
                exc_info=True,
            )
            return 0

    async def _run(self) -> None:
        while True:
            try:
                await asyncio.wait_for(self._wakeup.wait(), timeout=self.FLUSH_INTERVAL)
            except asyncio.TimeoutError:
                pass
            except asyncio.CancelledError:
                raise
            self._wakeup.clear()
            await self.flush()

    async def start(self) -> None:
        if self.active:
            return
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """Stop the flusher and write out whatever is still buffered."""
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        await self.flush()


_audit_buffer = AuditBuffer()


def get_audit_buffer() -> AuditBuffer:
    """The process-wide audit buffer (started at boot, drained on shutdown)."""
    return _audit_buffer


async def start_audit_buffer() -> None:
    await _audit_buffer.start()


async def stop_audit_buffer() -> None:
    await _audit_buffer.stop()


async def log_audit(
    action: str,
    *,
    level: str = "INFO",
    user_id: int | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    details: str | None = None,
    ip_address: str | None = None,
    session: AsyncSession | None = None,
) -> None:
    """Write audit entry to both the log file and the database.

    When 'session' is given, the DB row is added to that session so it
    commits (or rolls back) atomically with the caller's transaction. It avoids a phantom audit
    row surviving a rolled-back parent and avoids taking a second pooled
    connection while row locks are held. Such a row is never buffered — it has
    to share the caller's transaction.

    Without a session the row goes through the batching buffer when one is
    running, and straight to its own short-lived session otherwise.
    """
    # 1. File log
    log_level = _LOG_LEVELS.get(level, logging.INFO)
    parts = [f"action={action}"]
    if user_id is not None:
        parts.append(f"user={user_id}")
    if resource_type:
        parts.append(f"resource={resource_type}")
    if resource_id:
        parts.append(f"id={resource_id}")
    if details:
        parts.append(details)
    if ip_address:
        parts.append(f"ip={ip_address}")
    audit_logger.log(log_level, " | ".join(parts))

    # 2. Database log
    try:
        if session is not None:
            # Enlist in the caller's transaction; the caller's commit/rollback decides this row's fate.
            session.add(AuditLog(
                level=level,
                user_id=user_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                details=details,
                ip_address=ip_address,
            ))
            return

        # Stamped now, not at flush time, so a batched row keeps the moment it describes rather than the moment it was written.
        row = {
            "timestamp": datetime.now(timezone.utc),
            "level": level,
            "user_id": user_id,
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "details": details,
            "ip_address": ip_address,
        }
        if _audit_buffer.add(row):
            return

        async with Database().session() as s:
            await s.execute(insert(AuditLog), [row])
    except Exception:
        audit_logger.warning("Failed to write audit entry to DB", exc_info=True)


def log_audit_bg(action: str, **kwargs) -> None:
    """Schedule log_audit without blocking the caller.

    For request-path call sites where the reply must not wait for the audit
    INSERT. Not usable with session= — an enlisted row must stay inside the
    caller's transaction, so those calls remain awaited.
    """
    from bot.database.methods.cache_utils import safe_create_task
    safe_create_task(log_audit(action, **kwargs))
