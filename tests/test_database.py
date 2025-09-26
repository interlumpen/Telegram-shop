import pytest
import asyncio
from datetime import datetime
from decimal import Decimal
from unittest.mock import patch, AsyncMock

from bot.database import Database
from bot.database.models import User, Categories, Goods, ItemValues, BoughtGoods, Operations, Payments, \
    ReferralEarnings
from bot.database.methods import (
    create_user, check_user, get_user_count, create_category, check_category, delete_category, update_category,
    create_item, check_item, delete_item, add_values_to_item, select_item_values_amount, check_value, create_operation,
    select_user_operations, process_payment_with_referral, buy_item_transaction, get_referral_earnings_stats
)


# Global cache mock fixture
@pytest.fixture(autouse=True)
def mock_cache_system():
    """Mock the entire cache system to avoid warnings"""
    # Create a mock cache manager that doesn't actually do anything
    mock_cache = AsyncMock()
    mock_cache.delete = AsyncMock(return_value=True)
    mock_cache.invalidate_pattern = AsyncMock(return_value=0)
    mock_cache.scan_iter = AsyncMock(return_value=AsyncMockIterator([]))

    # Mock all cache-related functions completely
    with patch('bot.misc.cache.get_cache_manager', return_value=mock_cache):
        with patch('bot.database.methods.read.get_cache_manager', return_value=mock_cache):
            with patch('bot.database.methods.cache_utils.safe_create_task'):
                with patch('bot.database.methods.read.invalidate_category_cache', new_callable=AsyncMock):
                    with patch('bot.database.methods.read.invalidate_item_cache', new_callable=AsyncMock):
                        with patch('bot.database.methods.read.invalidate_user_cache', new_callable=AsyncMock):
                            with patch('bot.database.methods.read.invalidate_stats_cache', new_callable=AsyncMock):
                                # Also patch any CacheManager instances that might exist
                                with patch('bot.misc.cache.CacheManager'):
                                    yield


class AsyncMockIterator:
    """Helper class to mock async iterator for Redis scan_iter"""

    def __init__(self, items):
        self.items = items
        self.index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.index >= len(self.items):
            raise StopAsyncIteration
        item = self.items[self.index]
        self.index += 1
        return item


class TestDatabaseMethods:
    """Test suite for database methods"""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test database before each test"""
        # Ensure we have a clean database state
        with Database().session() as s:
            # Clean up test data
            s.query(ReferralEarnings).delete()
            s.query(Payments).delete()
            s.query(Operations).delete()
            s.query(BoughtGoods).delete()
            s.query(ItemValues).delete()
            s.query(Goods).delete()
            s.query(Categories).delete()
            s.query(User).filter(User.telegram_id.in_([999001, 999002, 999003])).delete()
            s.commit()
        yield
        # Cleanup after test
        with Database().session() as s:
            s.query(ReferralEarnings).delete()
            s.query(Payments).delete()
            s.query(Operations).delete()
            s.query(BoughtGoods).delete()
            s.query(ItemValues).delete()
            s.query(Goods).delete()
            s.query(Categories).delete()
            s.query(User).filter(User.telegram_id.in_([999001, 999002, 999003])).delete()
            s.commit()

    def test_user_crud_operations(self):
        """Test user creation, reading, and updating"""
        user_id = 999001
        reg_date = datetime.now()

        # Create user
        create_user(user_id, reg_date, referral_id=None, role=1)

        # Check user exists
        user = check_user(user_id)
        assert user is not None
        assert user["telegram_id"] == user_id
        assert user["balance"] == Decimal("0")
        assert user["role_id"] == 1

        # Test duplicate creation (should not raise error)
        create_user(user_id, reg_date, referral_id=None, role=1)

        # Check user count
        initial_count = get_user_count()
        assert initial_count > 0

    def test_referral_system(self):
        """Test referral user creation and linking"""
        referrer_id = 999001
        referral_id = 999002

        # Create referrer
        create_user(referrer_id, datetime.now(), referral_id=None, role=1)

        # Create referral with referrer
        create_user(referral_id, datetime.now(), referral_id=referrer_id, role=1)

        user = check_user(referral_id)
        assert user["referral_id"] == referrer_id

    def test_category_operations(self):
        """Test category CRUD operations"""
        category_name = "TestCategory"

        # Create category
        create_category(category_name)

        # Check category exists
        category = check_category(category_name)
        assert category is not None
        assert category['name'] == category_name

        # Update category
        new_name = "UpdatedCategory"
        update_category(category_name, new_name)

        # Check old name doesn't exist
        assert check_category(category_name) is None

        # Check new name exists
        assert check_category(new_name) is not None

        # Delete category
        delete_category(new_name)
        assert check_category(new_name) is None

    def test_goods_operations(self):
        """Test goods/items CRUD operations"""
        # Setup
        category_name = "TestCategory"
        item_name = "TestItem"
        create_category(category_name)

        # Create item
        create_item(item_name, "Test description", 100, category_name)

        # Check item exists
        item = check_item(item_name)
        assert item is not None
        assert item['name'] == item_name
        assert item['price'] == 100

        # Add values to item
        assert add_values_to_item(item_name, "value1", False) == True
        assert add_values_to_item(item_name, "value2", False) == True
        # Duplicate should fail
        assert add_values_to_item(item_name, "value1", False) == False

        # Check values count
        assert select_item_values_amount(item_name) == 2

        # Test infinite item
        add_values_to_item(item_name, "infinite_value", True)
        assert check_value(item_name) == True  # Has infinite value

        # Delete item
        delete_item(item_name)
        assert check_item(item_name) is None

    def test_operations_tracking(self):
        """Test balance operations tracking"""
        user_id = 999001
        create_user(user_id, datetime.now(), referral_id=None, role=1)

        # Create operations
        op1_value = 100
        op2_value = 200
        create_operation(user_id, op1_value, datetime.now())
        create_operation(user_id, op2_value, datetime.now())

        # Check operations
        operations = select_user_operations(user_id)
        assert len(operations) == 2
        assert sum(operations) == op1_value + op2_value

    def test_payment_processing(self):
        """Test payment processing with idempotency"""
        user_id = 999001
        create_user(user_id, datetime.now(), referral_id=None, role=1)

        amount = Decimal("500")
        provider = "test"
        external_id = "test_payment_001"

        # First payment should succeed
        success1, msg1 = process_payment_with_referral(
            user_id=user_id,
            amount=amount,
            provider=provider,
            external_id=external_id,
            referral_percent=0
        )
        assert success1 == True
        assert msg1 == "success"

        # Duplicate payment should fail
        success2, msg2 = process_payment_with_referral(
            user_id=user_id,
            amount=amount,
            provider=provider,
            external_id=external_id,
            referral_percent=0
        )
        assert success2 == False
        assert msg2 == "already_processed"

        # Check user balance updated only once
        user = check_user(user_id)
        assert user["balance"] == amount

    def test_referral_earnings(self):
        """Test referral earnings system"""
        referrer_id = 999001
        referral_id = 999002

        # Setup users
        create_user(referrer_id, datetime.now(), referral_id=None, role=1)
        create_user(referral_id, datetime.now(), referral_id=referrer_id, role=1)

        # Process payment with referral bonus
        amount = Decimal("1000")
        referral_percent = 10

        success, msg = process_payment_with_referral(
            user_id=referral_id,
            amount=amount,
            provider="test",
            external_id="ref_payment_001",
            referral_percent=referral_percent
        )

        assert success == True

        # Check referrer got bonus
        referrer = check_user(referrer_id)
        expected_bonus = (Decimal(referral_percent) / Decimal(100)) * amount
        assert referrer["balance"] == expected_bonus

        # Check earnings stats
        stats = get_referral_earnings_stats(referrer_id)
        assert stats['total_earnings_count'] == 1
        assert stats['total_amount'] == expected_bonus
        assert stats['active_referrals_count'] == 1

    @pytest.mark.asyncio
    async def test_concurrent_database_access(self):
        """Test database handles concurrent access correctly"""
        user_id = 999001
        create_user(user_id, datetime.now(), referral_id=None, role=1)

        # Create multiple concurrent operations
        async def create_operation_async(value):
            await asyncio.sleep(0.01)  # Small delay to simulate real conditions
            create_operation(user_id, value, datetime.now())

        # Run 10 concurrent operations
        tasks = [create_operation_async(i * 10) for i in range(1, 11)]
        await asyncio.gather(*tasks)

        # Check all operations were recorded
        operations = select_user_operations(user_id)
        assert len(operations) == 10
        assert sum(operations) == sum(i * 10 for i in range(1, 11))

    def test_transaction_rollback(self):
        """Test transaction rollback on error"""
        user_id = 999001
        category_name = "TestCategory"
        item_name = "TestItem"

        # Setup
        create_user(user_id, datetime.now(), referral_id=None, role=1)
        create_category(category_name)
        create_item(item_name, "Test", 1000, category_name)
        add_values_to_item(item_name, "value1", False)

        # User has 0 balance, purchase should fail
        success, msg, data = buy_item_transaction(user_id, item_name)

        assert success == False
        assert msg == "insufficient_funds"

        # Check item still available
        assert select_item_values_amount(item_name) == 1

        # Check user balance unchanged
        user = check_user(user_id)
        assert user["balance"] == Decimal("0")
