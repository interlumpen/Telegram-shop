import asyncio
from decimal import Decimal

from bot.database.methods.read import invalidate_user_cache, invalidate_item_cache, invalidate_category_cache, \
    invalidate_stats_cache

from bot.database.methods.update import update_balance, set_role, \
    set_user_blocked
from bot.database.methods.delete import delete_item, delete_category
from bot.database.methods.transactions import buy_item_transaction, \
    process_payment_with_referral


class TestCacheInvalidationFunctions:
    """Test that each invalidation function removes the expected keys."""

    async def test_invalidate_user_cache(self, fake_cache):
        fake_cache.store["user:123"] = {"telegram_id": 123, "balance": 0}
        fake_cache.store["role:123"] = 1
        fake_cache.store["user_stats:123:x"] = 42
        fake_cache.store["user_items:123:y"] = [1, 2]

        await invalidate_user_cache(123)

        assert "user:123" not in fake_cache.store
        assert "role:123" not in fake_cache.store
        assert "user_stats:123:x" not in fake_cache.store
        assert "user_items:123:y" not in fake_cache.store

    async def test_invalidate_item_cache(self, fake_cache):
        fake_cache.store["item:Test"] = {"name": "Test"}
        fake_cache.store["item_info:Test"] = {"name": "Test", "price": 100}
        fake_cache.store["item_values:Test"] = 5
        fake_cache.store["category:Cat1"] = {"name": "Cat1"}

        await invalidate_item_cache("Test")

        assert "item:Test" not in fake_cache.store
        assert "item_info:Test" not in fake_cache.store
        assert "item_values:Test" not in fake_cache.store
        assert "category:Cat1" not in fake_cache.store

    async def test_invalidate_category_cache(self, fake_cache):
        fake_cache.store["category:Cat"] = {"name": "Cat"}
        fake_cache.store["category_items:Cat:page1"] = [1, 2, 3]

        await invalidate_category_cache("Cat")

        assert "category:Cat" not in fake_cache.store
        assert "category_items:Cat:page1" not in fake_cache.store

    async def test_invalidate_stats_cache(self, fake_cache):
        fake_cache.store["stats:daily"] = 10
        fake_cache.store["stats:total"] = 100
        fake_cache.store["user_count"] = 50
        fake_cache.store["admin_count"] = 3

        await invalidate_stats_cache()

        assert "stats:daily" not in fake_cache.store
        assert "stats:total" not in fake_cache.store
        assert "user_count" not in fake_cache.store
        assert "admin_count" not in fake_cache.store

    async def test_invalidate_preserves_other_keys(self, fake_cache):
        fake_cache.store["user:123"] = {"telegram_id": 123}
        fake_cache.store["user:456"] = {"telegram_id": 456}

        await invalidate_user_cache(123)

        assert "user:123" not in fake_cache.store
        assert "user:456" in fake_cache.store


class TestCacheInvalidationAfterMutations:
    """Test that DB mutation functions trigger the correct cache invalidation."""

    async def test_update_balance_invalidates_cache(self, user_factory, fake_cache):
        user = await user_factory(telegram_id=100001)
        user_id = user["telegram_id"]
        fake_cache.store[f"user:{user_id}"] = {"telegram_id": user_id, "balance": 0}

        await update_balance(user_id, 500)
        await asyncio.sleep(0)

        assert f"user:{user_id}" not in fake_cache.store

    async def test_set_role_invalidates_cache(self, user_factory, fake_cache):
        user = await user_factory(telegram_id=100001)
        user_id = user["telegram_id"]
        fake_cache.store[f"user:{user_id}"] = {"telegram_id": user_id}

        await set_role(user_id, 2)
        await asyncio.sleep(0)

        assert f"user:{user_id}" not in fake_cache.store

    async def test_set_user_blocked_invalidates_cache(self, user_factory, fake_cache):
        user = await user_factory(telegram_id=100001)
        user_id = user["telegram_id"]
        fake_cache.store[f"user:{user_id}"] = {"telegram_id": user_id}

        await set_user_blocked(user_id, True)
        await asyncio.sleep(0)

        assert f"user:{user_id}" not in fake_cache.store

    async def test_delete_item_invalidates_cache(self, item_factory, fake_cache):
        item_name = "TestItem"
        await item_factory(name=item_name, price=100, values=[("value1", False)])
        fake_cache.store[f"item:{item_name}"] = {"name": item_name}

        await delete_item(item_name)
        await asyncio.sleep(0)

        assert f"item:{item_name}" not in fake_cache.store

    async def test_delete_category_invalidates_cache(self, category_factory, fake_cache):
        cat_name = "TestCategory"
        await category_factory(cat_name)
        fake_cache.store[f"category:{cat_name}"] = {"name": cat_name}

        await delete_category(cat_name)
        await asyncio.sleep(0)

        assert f"category:{cat_name}" not in fake_cache.store

    async def test_buy_item_invalidates_user_cache(
            self, user_factory, item_factory, fake_cache
    ):
        user = await user_factory(telegram_id=100001, balance=500)
        user_id = user["telegram_id"]
        await item_factory(name="TestItem", price=100, values=[("secret_value", False)])
        fake_cache.store[f"user:{user_id}"] = {"telegram_id": user_id, "balance": 500}

        success, msg, data = await buy_item_transaction(user_id, "TestItem")
        await asyncio.sleep(0)

        assert success is True
        assert f"user:{user_id}" not in fake_cache.store

    async def test_payment_invalidates_user_and_stats_cache(
            self, user_factory, fake_cache
    ):
        user = await user_factory(telegram_id=100001)
        user_id = user["telegram_id"]
        fake_cache.store[f"user:{user_id}"] = {"telegram_id": user_id, "balance": 0}
        fake_cache.store["user_count"] = 1

        success, msg = await process_payment_with_referral(
            user_id=user_id,
            amount=Decimal("500"),
            provider="stars",
            external_id="pay_001",
            referral_percent=0,
        )
        await asyncio.sleep(0)

        assert success is True
        assert f"user:{user_id}" not in fake_cache.store
        assert "user_count" not in fake_cache.store

    async def test_payment_with_referral_invalidates_referrer_cache(
            self, user_factory, fake_cache
    ):
        referrer = await user_factory(telegram_id=200001)
        referrer_id = referrer["telegram_id"]
        user = await user_factory(telegram_id=100001, referral_id=referrer_id)
        user_id = user["telegram_id"]

        fake_cache.store[f"user:{referrer_id}"] = {
            "telegram_id": referrer_id,
            "balance": 0,
        }

        success, msg = await process_payment_with_referral(
            user_id=user_id,
            amount=Decimal("1000"),
            provider="stars",
            external_id="pay_002",
            referral_percent=10,
        )
        await asyncio.sleep(0)

        assert success is True
        assert f"user:{referrer_id}" not in fake_cache.store
