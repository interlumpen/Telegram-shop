import pytest
import asyncio
from decimal import Decimal
from datetime import datetime
from unittest.mock import MagicMock, AsyncMock

from bot.database import Database
from bot.database.models import User, Goods, ItemValues, Categories, Payments
from bot.database.methods import buy_item_transaction, process_payment_with_referral
from bot.middleware import RateLimiter, RateLimitConfig
from bot.misc import BroadcastManager, BroadcastStats, LazyPaginator
from aiogram.exceptions import TelegramForbiddenError
from aiogram.methods import SendMessage


class TestTransactionalSafety:
    """Test suite for transactional operations safety"""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test database before each test"""
        with Database().session() as s:
            # Clean up test data
            s.query(User).filter(User.telegram_id.in_([111, 222])).delete()
            s.query(Goods).filter(Goods.name == "test_item").delete()
            s.query(Categories).filter(Categories.name == "test_category").delete()
            s.commit()
        yield
        # Cleanup after test
        with Database().session() as s:
            s.query(User).filter(User.telegram_id.in_([111, 222])).delete()
            s.query(Goods).filter(Goods.name == "test_item").delete()
            s.query(Categories).filter(Categories.name == "test_category").delete()
            s.commit()

    @pytest.mark.asyncio
    async def test_concurrent_purchase_safety(self):
        """Test that only one user can buy the last product"""
        # Prepare test data
        with Database().session() as s:
            # Create test users
            user1 = User(telegram_id=111, balance=Decimal("1000"),
                         registration_date=datetime.now(), role_id=1)
            user2 = User(telegram_id=222, balance=Decimal("1000"),
                         registration_date=datetime.now(), role_id=1)
            s.add(user1)
            s.add(user2)

            # Create category and product
            category = Categories(name="test_category")
            s.add(category)

            goods = Goods(
                "test_item",
                Decimal("100"),
                "Test",
                "test_category"
            )
            s.add(goods)

            # Add ONLY ONE item
            item_value = ItemValues(name="test_item", value="SECRET_KEY", is_infinity=False)
            s.add(item_value)
            s.commit()

        # Parallel buying
        async def buy_user1():
            await asyncio.sleep(0.01)  # Slight delay
            return buy_item_transaction(111, "test_item")

        async def buy_user2():
            return buy_item_transaction(222, "test_item")

        # Run at the same time
        results = await asyncio.gather(buy_user1(), buy_user2(), return_exceptions=True)

        # Check the results
        success_count = sum(1 for r in results if not isinstance(r, Exception) and r[0])
        failed_count = sum(1 for r in results if not isinstance(r, Exception) and not r[0])

        assert success_count == 1, "Only one must successfully buy"
        assert failed_count == 1, "One should get an error"

        # Check error messages
        for result in results:
            if not isinstance(result, Exception) and not result[0]:
                assert result[1] in ["out_of_stock", "transaction_error"], \
                    f"Unexpected error: {result[1]}"


class TestPaymentIdempotency:
    """Test suite for payment processing idempotency"""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup and cleanup test data"""
        with Database().session() as s:
            s.query(User).filter(User.telegram_id == 333).delete()
            s.query(Payments).filter(Payments.external_id == "payment_123").delete()
            s.commit()
        yield
        with Database().session() as s:
            s.query(User).filter(User.telegram_id == 333).delete()
            s.query(Payments).filter(Payments.external_id == "payment_123").delete()
            s.commit()

    def test_payment_idempotency(self):
        """Test that payment re-processing doesn't duplicate accruals"""
        # Preparation
        with Database().session() as s:
            user = User(telegram_id=333, balance=Decimal("0"),
                        registration_date=datetime.now(), role_id=1)
            s.add(user)
            s.commit()

        # First attempt to process the payment
        result1 = process_payment_with_referral(
            user_id=333,
            amount=Decimal("500"),
            provider="test",
            external_id="payment_123",
            referral_percent=0
        )

        # Second attempt with the same external_id
        result2 = process_payment_with_referral(
            user_id=333,
            amount=Decimal("500"),
            provider="test",
            external_id="payment_123",  # Same ID!
            referral_percent=0
        )

        assert result1[0] == True, "First payment must go through"
        assert result2[0] == False, "Second payment must be rejected"
        assert result2[1] == "already_processed", "Should have duplicate message"

        # Check balance - should be only 500, not 1000
        with Database().session() as s:
            user = s.query(User).filter(User.telegram_id == 333).one()
            assert user.balance == Decimal("500"), f"Balance should be 500, not {user.balance}"

            # Check payment records
            payments = s.query(Payments).filter(Payments.external_id == "payment_123").all()
            assert len(payments) == 1, "Should only have one payment record"


class TestRateLimiting:
    """Test suite for rate limiting functionality"""

    def test_global_rate_limiting(self):
        """Test global request rate limiting"""
        config = RateLimitConfig(
            global_limit=5,
            global_window=10,
            ban_duration=5
        )

        limiter = RateLimiter(config)
        user_id = 444

        # First 5 requests should pass
        for i in range(5):
            assert limiter.check_global_limit(user_id), f"Request {i + 1} must pass"

        # 6th request should be blocked
        assert not limiter.check_global_limit(user_id), "6th request must be blocked"

    def test_action_specific_limiting(self):
        """Test action-specific rate limits"""
        config = RateLimitConfig(
            global_limit=100,
            global_window=60,
            action_limits={
                'test_action': (2, 10)  # 2 times in 10 seconds
            }
        )

        limiter = RateLimiter(config)
        user_id = 555

        assert limiter.check_action_limit(user_id, 'test_action'), "1st action must pass"
        assert limiter.check_action_limit(user_id, 'test_action'), "2nd action must pass"
        assert not limiter.check_action_limit(user_id, 'test_action'), "3rd action must be blocked"

    def test_ban_mechanism(self):
        """Test user banning after limit exceeded"""
        config = RateLimitConfig(
            global_limit=5,
            global_window=10,
            ban_duration=5
        )

        limiter = RateLimiter(config)
        user_id = 444

        # Exceed limit
        for _ in range(6):
            limiter.check_global_limit(user_id)

        # Ban user
        limiter.ban_user(user_id)
        assert limiter.is_banned(user_id), "User should be banned"

        # Check wait time
        wait_time = limiter.get_wait_time(user_id)
        assert 0 < wait_time <= 5, f"Wait time should be 0-5 sec, got: {wait_time}"


class TestBroadcastSystem:
    """Test suite for broadcast/mailing system"""

    @pytest.mark.asyncio
    async def test_broadcast_with_failures(self):
        """Test broadcast handling with some failed messages"""
        # Mock bot
        bot_mock = AsyncMock()
        bot_mock.send_message = AsyncMock()

        # Setup: some users blocked the bot
        async def send_side_effect(chat_id, **kwargs):
            if chat_id in [3, 7]:  # These users blocked
                method = SendMessage(chat_id=chat_id, text=kwargs.get("text", ""))
                raise TelegramForbiddenError(method=method, message="Bot blocked by user")
            return MagicMock()

        bot_mock.send_message.side_effect = send_side_effect

        manager = BroadcastManager(
            bot=bot_mock,
            batch_size=3,
            batch_delay=0.01,
            retry_count=1
        )

        # User list
        user_ids = list(range(1, 11))  # 10 users

        # Progress tracking
        progress_calls = []

        async def progress_callback(stats: BroadcastStats):
            progress_calls.append(stats.sent + stats.failed)

        # Start broadcast
        stats = await manager.broadcast(
            user_ids=user_ids,
            text="Test message",
            progress_callback=progress_callback
        )

        # Verify results
        assert stats.total == 10
        assert stats.sent == 8
        assert stats.failed == 2
        assert stats.success_rate == 80.0
        assert stats.duration is not None
        assert len(progress_calls) > 0

    @pytest.mark.asyncio
    async def test_broadcast_cancellation(self):
        """Test broadcast cancellation functionality"""
        bot_mock = AsyncMock()

        # Create an asynchronous function that expects sleep correctly
        async def slow_send(*args, **kwargs):
            await asyncio.sleep(0.1)
            return MagicMock()

        bot_mock.send_message = AsyncMock(side_effect=slow_send)

        manager = BroadcastManager(bot=bot_mock)
        user_ids = list(range(1, 101))  # 100 users

        # Start broadcast and cancel immediately
        task = asyncio.create_task(
            manager.broadcast(user_ids=user_ids, text="Test")
        )

        await asyncio.sleep(0.05)  # Let it start
        manager.cancel()

        stats = await task

        # Should be cancelled before completion
        assert stats.sent + stats.failed < 100


class TestLazyPaginationSystem:
    """Test suite for lazy pagination functionality"""

    @pytest.mark.asyncio
    async def test_pagination_basics(self):
        """Test basic pagination functionality"""
        call_counter = {"count": 0}

        async def mock_query(offset=0, limit=10, count_only=False):
            call_counter["count"] += 1
            if count_only:
                return 100
            return [f"item_{i}" for i in range(offset, min(offset + limit, 100))]

        paginator = LazyPaginator(
            query_func=mock_query,
            per_page=10,
            cache_pages=3
        )

        # Get first page
        page1 = await paginator.get_page(0)
        assert len(page1) == 10
        assert page1[0] == "item_0"

        # Request same page (should use cache)
        calls_before = call_counter["count"]
        page1_cached = await paginator.get_page(0)
        assert call_counter["count"] == calls_before  # No new query
        assert page1 == page1_cached

    @pytest.mark.asyncio
    async def test_pagination_boundaries(self):
        """Test pagination boundary conditions"""

        async def mock_query(offset=0, limit=10, count_only=False):
            if count_only:
                return 25  # Not evenly divisible by page size
            return list(range(offset, min(offset + limit, 25)))

        paginator = LazyPaginator(mock_query, per_page=10)

        # Last page should have partial results
        last_page = await paginator.get_page(2)
        assert len(last_page) == 5  # 25 - 20 = 5 items

        # Beyond last page should be empty
        beyond_page = await paginator.get_page(10)
        assert beyond_page == []

        # Total pages calculation
        total_pages = await paginator.get_total_pages()
        assert total_pages == 3  # 25 items / 10 per page = 3 pages
