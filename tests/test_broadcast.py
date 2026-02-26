import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

from aiogram.exceptions import TelegramForbiddenError

from bot.misc.services.broadcast_system import BroadcastManager, BroadcastStats


class TestBroadcastStats:

    def test_success_rate_all_sent(self):
        stats = BroadcastStats(total=10, sent=10, failed=0)
        assert stats.success_rate == 100.0

    def test_success_rate_partial(self):
        stats = BroadcastStats(total=10, sent=7, failed=3)
        assert stats.success_rate == 70.0

    def test_success_rate_zero_total(self):
        stats = BroadcastStats(total=0, sent=0, failed=0)
        assert stats.success_rate == 0

    def test_duration(self):
        start = datetime(2026, 1, 1, 12, 0, 0)
        end = datetime(2026, 1, 1, 12, 0, 10)
        stats = BroadcastStats(start_time=start, end_time=end)
        assert stats.duration == 10.0

    def test_duration_none_when_not_finished(self):
        stats = BroadcastStats(start_time=datetime.now())
        assert stats.duration is None


class TestBroadcastManager:

    def setup_method(self):
        self.bot = AsyncMock()
        self.manager = BroadcastManager(
            bot=self.bot,
            batch_size=5,
            batch_delay=0,  # No delay in tests
            retry_count=1,
        )

    @pytest.mark.asyncio
    async def test_broadcast_all_success(self):
        self.bot.send_message = AsyncMock(return_value=True)
        user_ids = [1, 2, 3, 4, 5]
        stats = await self.manager.broadcast(user_ids, "Hello!")
        assert stats.sent == 5
        assert stats.failed == 0
        assert stats.total == 5

    @pytest.mark.asyncio
    async def test_broadcast_partial_failure(self):
        call_count = 0

        async def send_with_failures(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count % 3 == 0:
                raise TelegramForbiddenError(method=MagicMock(), message="Forbidden")
            return True

        self.bot.send_message = send_with_failures
        user_ids = list(range(1, 10))
        stats = await self.manager.broadcast(user_ids, "Hello!")
        assert stats.sent > 0
        assert stats.failed > 0
        assert stats.sent + stats.failed == stats.total

    @pytest.mark.asyncio
    async def test_broadcast_forbidden_user(self):
        self.bot.send_message = AsyncMock(
            side_effect=TelegramForbiddenError(method=MagicMock(), message="Forbidden")
        )
        stats = await self.manager.broadcast([1, 2, 3], "Hello!")
        assert stats.sent == 0
        assert stats.failed == 3

    @pytest.mark.asyncio
    async def test_broadcast_cancel(self):
        send_count = 0

        async def slow_send(**kwargs):
            nonlocal send_count
            send_count += 1
            return True

        self.bot.send_message = slow_send
        # Use batch_size=2 so multiple batches
        self.manager.batch_size = 2
        user_ids = list(range(1, 11))

        # Cancel after first batch via progress callback
        def cancel_after_first(stats):
            if stats.sent >= 2:
                self.manager.cancel()

        stats = await self.manager.broadcast(
            user_ids, "Hello!", progress_callback=cancel_after_first
        )
        # Should have cancelled before sending to all 10
        assert stats.sent < 10

    @pytest.mark.asyncio
    async def test_broadcast_progress_callback(self):
        self.bot.send_message = AsyncMock(return_value=True)
        self.manager.batch_size = 3
        progress_calls = []

        def on_progress(stats):
            progress_calls.append(stats.sent)

        user_ids = list(range(1, 7))
        await self.manager.broadcast(
            user_ids, "Hello!", progress_callback=on_progress
        )
        assert len(progress_calls) == 2  # 2 batches of 3

    @pytest.mark.asyncio
    async def test_broadcast_stats_have_times(self):
        self.bot.send_message = AsyncMock(return_value=True)
        stats = await self.manager.broadcast([1], "Hello!")
        assert stats.start_time is not None
        assert stats.end_time is not None
        assert stats.duration is not None
        assert stats.duration >= 0
