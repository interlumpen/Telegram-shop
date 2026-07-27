import pytest
from sqlalchemy import select

from bot.database.methods.audit import log_audit, log_audit_bg
from bot.database.main import Database
from bot.database.models.main import AuditLog


class TestLogAudit:

    async def test_creates_audit_record(self):
        await log_audit("test_action", user_id=12345, details="test details")

        async with Database().session() as s:
            entry = (await s.execute(select(AuditLog).filter(AuditLog.action == "test_action"))).scalars().first()
            assert entry is not None
            assert entry.user_id == 12345
            assert entry.details == "test details"
            assert entry.level == "INFO"

    async def test_warning_level(self):
        await log_audit("warn_action", level="WARNING", details="warning test")

        async with Database().session() as s:
            entry = (await s.execute(select(AuditLog).filter(AuditLog.action == "warn_action"))).scalars().first()
            assert entry is not None
            assert entry.level == "WARNING"

    async def test_all_optional_fields(self):
        await log_audit(
            "full_action",
            level="ERROR",
            user_id=99999,
            resource_type="payment",
            resource_id="PAY-123",
            details="full test",
            ip_address="192.168.1.1",
        )

        async with Database().session() as s:
            entry = (await s.execute(select(AuditLog).filter(AuditLog.action == "full_action"))).scalars().first()
            assert entry is not None
            assert entry.resource_type == "payment"
            assert entry.resource_id == "PAY-123"
            assert entry.ip_address == "192.168.1.1"
            assert entry.level == "ERROR"

    async def test_minimal_fields(self):
        await log_audit("minimal_action")

        async with Database().session() as s:
            entry = (await s.execute(select(AuditLog).filter(AuditLog.action == "minimal_action"))).scalars().first()
            assert entry is not None
            assert entry.user_id is None
            assert entry.resource_type is None
            assert entry.details is None
            assert entry.ip_address is None
            assert entry.timestamp is not None

    async def test_log_audit_bg_creates_record(self):
        log_audit_bg("bg_action", user_id=54321, details="bg details")

        # Returns immediately; drain the scheduled background task first.
        import asyncio
        pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        await asyncio.gather(*pending)

        async with Database().session() as s:
            entry = (await s.execute(select(AuditLog).filter(AuditLog.action == "bg_action"))).scalars().first()
            assert entry is not None
            assert entry.user_id == 54321
            assert entry.details == "bg details"


class TestAuditBuffer:
    async def _count(self, action: str) -> int:
        from sqlalchemy import func
        async with Database().session() as s:
            return (await s.execute(
                select(func.count(AuditLog.id)).where(AuditLog.action == action)
            )).scalar()

    async def test_writes_through_when_no_flusher_runs(self):
        from bot.database.methods.audit import get_audit_buffer

        assert get_audit_buffer().active is False
        await log_audit("direct_action", user_id=1)

        assert await self._count("direct_action") == 1

    async def test_buffered_rows_land_on_flush(self):
        from bot.database.methods.audit import start_audit_buffer, stop_audit_buffer

        await start_audit_buffer()
        try:
            for i in range(5):
                await log_audit("buffered_action", user_id=i)
            # Still in memory: the batch has neither filled up nor timed out.
            assert await self._count("buffered_action") == 0
        finally:
            await stop_audit_buffer()

        # Shutdown drains the buffer rather than dropping it.
        assert await self._count("buffered_action") == 5

    async def test_full_batch_flushes_without_waiting(self):
        import asyncio
        from bot.database.methods.audit import (
            AuditBuffer, get_audit_buffer, start_audit_buffer, stop_audit_buffer,
        )

        await start_audit_buffer()
        try:
            for i in range(AuditBuffer.MAX_BATCH):
                await log_audit("full_batch_action", user_id=i)

            # Hitting MAX_BATCH wakes the flusher instead of waiting out the interval.
            for _ in range(10):
                await asyncio.sleep(0)
                if await self._count("full_batch_action") == AuditBuffer.MAX_BATCH:
                    break

            assert await self._count("full_batch_action") == AuditBuffer.MAX_BATCH
            assert get_audit_buffer()._rows == []
        finally:
            await stop_audit_buffer()

    async def test_buffered_row_keeps_the_time_of_the_event(self):
        import datetime
        from bot.database.methods.audit import start_audit_buffer, stop_audit_buffer

        before = datetime.datetime.now(datetime.timezone.utc)
        await start_audit_buffer()
        try:
            await log_audit("timed_action", user_id=7)
        finally:
            await stop_audit_buffer()
        after = datetime.datetime.now(datetime.timezone.utc)

        async with Database().session() as s:
            entry = (await s.execute(
                select(AuditLog).where(AuditLog.action == "timed_action")
            )).scalars().first()

        ts = entry.timestamp
        if ts.tzinfo is None:  # SQLite hands back naive datetimes
            ts = ts.replace(tzinfo=datetime.timezone.utc)
        assert before <= ts <= after

    async def test_session_bound_rows_are_never_buffered(self):
        from bot.database.methods.audit import start_audit_buffer, stop_audit_buffer

        await start_audit_buffer()
        try:
            async with Database().session() as s:
                await log_audit("enlisted_action", user_id=8, session=s)
            # Committed with the caller's transaction, not held in the buffer.
            assert await self._count("enlisted_action") == 1
        finally:
            await stop_audit_buffer()

    async def test_enlisted_row_rolls_back_with_its_transaction(self):
        from bot.database.methods.audit import start_audit_buffer, stop_audit_buffer

        await start_audit_buffer()
        try:
            with pytest.raises(RuntimeError):
                async with Database().session() as s:
                    await log_audit("rolled_back_action", user_id=9, session=s)
                    raise RuntimeError("caller failed")

            assert await self._count("rolled_back_action") == 0
        finally:
            await stop_audit_buffer()

    async def test_a_failing_flush_does_not_grow_the_buffer(self, monkeypatch):
        from bot.database.methods.audit import get_audit_buffer, start_audit_buffer, stop_audit_buffer

        await start_audit_buffer()
        try:
            await log_audit("doomed_action", user_id=10)

            buf = get_audit_buffer()
            monkeypatch.setattr(
                "bot.database.methods.audit.Database",
                lambda: (_ for _ in ()).throw(RuntimeError("db down")),
            )
            assert await buf.flush() == 0
            # Dropped, not retried forever: the file log already has them.
            assert buf._rows == []
        finally:
            monkeypatch.undo()
            await stop_audit_buffer()
