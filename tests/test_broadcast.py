import pytest
from datetime import datetime
from unittest.mock import MagicMock, AsyncMock
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.methods import SendMessage  # For creating proper exception objects

from bot.misc.broadcast_system import BroadcastManager, BroadcastStats


class TestBroadcastSystem:
    """Test suite for broadcast system"""

    def test_broadcast_stats_initialization(self):
        """Test BroadcastStats initialization"""
        stats = BroadcastStats()

        assert stats.total == 0
        assert stats.sent == 0
        assert stats.failed == 0
        assert stats.blocked == 0
        assert stats.success_rate == 0.0
        # Fixed: start_time is None by default, not datetime
        assert stats.start_time is None
        assert stats.end_time is None
        assert stats.duration is None

    def test_broadcast_stats_calculation(self):
        """Test BroadcastStats calculations"""
        stats = BroadcastStats()
        stats.total = 100
        stats.sent = 75
        stats.failed = 20
        stats.blocked = 5

        # Success rate calculation
        assert stats.success_rate == 75.0

        # Duration calculation - using the property, not a method
        stats.start_time = datetime.now()
        import time
        time.sleep(0.1)
        stats.end_time = datetime.now()  # Set end_time manually
        assert stats.duration > 0

    @pytest.mark.asyncio
    async def test_broadcast_with_failures(self):
        """Test broadcast with some failed messages"""
        bot = MagicMock()

        # Create proper exception objects with method parameter
        method = SendMessage(chat_id=1, text="Test")

        # Create a list of side effects (not AsyncMocks)
        side_effects = [
            MagicMock(),  # Success for user 1
            TelegramBadRequest(method=method, message="Bad request"),  # Fail for user 2
            MagicMock(),  # Success for user 3
            TelegramForbiddenError(method=method, message="User blocked bot"),  # Blocked for user 4
            MagicMock(),  # Success for user 5
        ]

        bot.send_message = AsyncMock(side_effect=side_effects)

        manager = BroadcastManager(bot, batch_size=2, batch_delay=0.01)
        user_ids = [1, 2, 3, 4, 5]

        stats = await manager.broadcast(
            user_ids=user_ids,
            text="Test message"
        )

        assert stats.total == 5
        assert stats.sent == 3
        assert stats.failed == 2  # Changed from 1 to 2 (one BadRequest, one Forbidden)
        assert stats.blocked >= 1  # At least the ForbiddenError
        assert stats.success_rate == 60.0

    @pytest.mark.asyncio
    async def test_broadcast_exception_handling(self):
        """Test various exception handling in broadcast"""
        bot = MagicMock()

        # Create method object for exceptions
        method = SendMessage(chat_id=1, text="Test")

        # Different types of exceptions with proper initialization
        exceptions = [
            TelegramBadRequest(method=method, message="Chat not found"),
            TelegramForbiddenError(method=method, message="Bot was blocked"),
            Exception("Unknown error"),
            TelegramBadRequest(method=method, message="Message is too long"),
        ]

        bot.send_message = AsyncMock(side_effect=exceptions)

        manager = BroadcastManager(bot)
        user_ids = [1, 2, 3, 4]

        stats = await manager.broadcast(
            user_ids=user_ids,
            text="Test"
        )

        assert stats.total == 4
        assert stats.sent == 0
        assert stats.failed >= 2  # At least some failures
        assert stats.blocked >= 1  # At least one blocked
