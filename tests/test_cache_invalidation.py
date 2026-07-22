import asyncio
from decimal import Decimal

from bot.database.methods.read import invalidate_user_cache, invalidate_item_cache, invalidate_category_cache, \
    invalidate_stats_cache, check_value_cached

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
        fake_cache.store["auth:role:123"] = 1
        fake_cache.store["user_stats:123:x"] = 42
        fake_cache.store["user_items:123:y"] = [1, 2]

        await invalidate_user_cache(123)

        assert "user:123" not in fake_cache.store
        assert "role:123" not in fake_cache.store
        assert "auth:role:123" not in fake_cache.store
        assert "user_stats:123:x" not in fake_cache.store
        assert "user_items:123:y" not in fake_cache.store

    async def test_invalidate_user_cache_drops_middleware_role_entry(self, fake_cache):
        import time as _time
        from bot.middleware.security import (
            AuthenticationMiddleware, set_auth_middleware, get_auth_middleware,
        )
        prev = get_auth_middleware()
        mw = AuthenticationMiddleware()
        mw.admin_cache[123] = (4, _time.time())
        mw.blocked_users.add(123)
        set_auth_middleware(mw)
        try:
            await invalidate_user_cache(123)
            assert 123 not in mw.admin_cache
            # Only the role entry is dropped; block state must not change.
            assert 123 in mw.blocked_users
        finally:
            set_auth_middleware(prev)

    async def test_invalidate_item_cache(self, fake_cache):
        fake_cache.store["item:Test"] = {"name": "Test"}
        fake_cache.store["item_info:Test"] = {"name": "Test", "price": 100}
        fake_cache.store["item_values:Test"] = 5
        fake_cache.store["item_infinite:Test"] = True
        fake_cache.store["category:Cat1"] = {"name": "Cat1"}

        await invalidate_item_cache("Test")

        assert "item:Test" not in fake_cache.store
        assert "item_info:Test" not in fake_cache.store
        assert "item_values:Test" not in fake_cache.store
        assert "item_infinite:Test" not in fake_cache.store
        assert "category:Cat1" in fake_cache.store

    async def test_check_value_cached_serves_from_cache(self, fake_cache, monkeypatch):
        calls = 0

        async def fake_check_value(item_name):
            nonlocal calls
            calls += 1
            return False

        monkeypatch.setattr('bot.database.methods.read.check_value', fake_check_value)

        assert await check_value_cached("CachedItem") is False
        assert await check_value_cached("CachedItem") is False
        # Second call must be a cache hit (False is cached too).
        assert calls == 1

    async def test_invalidate_item_cache_with_category_drops_only_that_key(self, fake_cache):
        fake_cache.store["item_info:Test"] = {"name": "Test"}
        fake_cache.store["category:Cat1"] = {"name": "Cat1"}
        fake_cache.store["category:Other"] = {"name": "Other"}

        await invalidate_item_cache("Test", category_name="Cat1")

        assert "item_info:Test" not in fake_cache.store
        assert "category:Cat1" not in fake_cache.store
        assert "category:Other" in fake_cache.store  # untouched

    async def test_invalidate_category_cache(self, fake_cache):
        fake_cache.store["category:Cat"] = {"name": "Cat"}
        fake_cache.store["category_items:Cat:page1"] = [1, 2, 3]
        fake_cache.store["category_items:Cat:count"] = 3
        fake_cache.store["categories:count"] = 7

        await invalidate_category_cache("Cat")

        assert "category:Cat" not in fake_cache.store
        assert "category_items:Cat:page1" not in fake_cache.store
        assert "category_items:Cat:count" not in fake_cache.store
        assert "categories:count" not in fake_cache.store

    async def test_paginator_counts_are_cached_and_invalidated(self, fake_cache, category_factory):
        from bot.database.methods.lazy_queries import query_categories, query_items_in_category
        from bot.database.methods.create import create_item

        await category_factory("CountCat")

        # First count goes to the DB and lands in the cache...
        assert await query_categories(count_only=True) >= 1
        assert "categories:count" in fake_cache.store
        # ...subsequent counts are served from it.
        fake_cache.store["categories:count"] = 99
        assert await query_categories(count_only=True) == 99

        assert await query_items_in_category("CountCat", count_only=True) == 0
        assert fake_cache.store["category_items:CountCat:count"] == 0

        # Creating an item drops the cached per-category count
        # (drain the scheduled invalidation task first).
        await create_item("CountItem", "d", 10, "CountCat")
        pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        await asyncio.gather(*pending)
        assert "category_items:CountCat:count" not in fake_cache.store
        assert await query_items_in_category("CountCat", count_only=True) == 1

    async def test_invalidate_stats_cache(self, fake_cache):
        import datetime as _dt
        today_local = _dt.date.today().isoformat()
        today_utc = _dt.datetime.now(_dt.timezone.utc).date().isoformat()
        # Real key shapes: async_cached appends a colon to zero-arg functions;
        # stats:daily is keyed by date.
        fake_cache.store[f"stats:daily:{today_local}"] = 10
        fake_cache.store[f"stats:daily:{today_utc}"] = 10
        fake_cache.store["stats:global"] = 100
        fake_cache.store["user_count:"] = 50
        fake_cache.store["admin_count:"] = 3
        fake_cache.store["stats:daily:2000-01-01"] = 1  # old date — janitor's job

        await invalidate_stats_cache()

        assert f"stats:daily:{today_local}" not in fake_cache.store
        assert f"stats:daily:{today_utc}" not in fake_cache.store
        assert "stats:global" not in fake_cache.store
        assert "user_count:" not in fake_cache.store
        assert "admin_count:" not in fake_cache.store
        # Targeted invalidation intentionally leaves stale dated keys to the
        # hourly scheduler sweep.
        assert "stats:daily:2000-01-01" in fake_cache.store

    async def test_async_cached_single_flight(self, fake_cache):
        from bot.database.methods.read import async_cached

        started = 0
        release = asyncio.Event()

        @async_cached(ttl=60, key_prefix="sf_test")
        async def slow(key):
            nonlocal started
            started += 1
            await release.wait()
            return 42

        t1 = asyncio.create_task(slow("k"))
        t2 = asyncio.create_task(slow("k"))
        await asyncio.sleep(0)  # let both tasks reach the miss path
        await asyncio.sleep(0)
        release.set()

        assert await t1 == 42
        assert await t2 == 42
        # Both callers got the value, but the body ran exactly once.
        assert started == 1
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
        fake_cache.store["user_count:"] = 1

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
        assert "user_count:" not in fake_cache.store

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


class TestWebPanelStockEdits:
    def _request(self):
        from unittest.mock import MagicMock
        request = MagicMock()
        request.client.host = "127.0.0.1"
        return request

    async def _fire(self, method, *args):
        from unittest.mock import patch

        scheduled = []
        with patch('bot.web.admin.safe_create_task', side_effect=scheduled.append):
            await method(*args)
        for coro in scheduled:
            await coro

    async def _stock_row(self, item_name: str):
        from sqlalchemy import select
        from bot.database.main import Database
        from bot.database.models.main import Goods, ItemValues

        async with Database().session() as s:
            item_id = (await s.execute(select(Goods.id).where(Goods.name == item_name))).scalar()
            return (await s.execute(
                select(ItemValues).where(ItemValues.item_id == item_id)
            )).scalars().first()

    async def test_create_invalidates_item_cache(self, fake_cache, item_factory):
        from bot.web.admin import ItemValuesAdmin

        await item_factory(name="PanelItem", price=10, values=[("v1", False)])
        row = await self._stock_row("PanelItem")
        fake_cache.store["item_values:PanelItem"] = 0   # the stale "out of stock" read

        await self._fire(ItemValuesAdmin().after_model_change, {}, row, True, self._request())

        assert "item_values:PanelItem" not in fake_cache.store

    async def test_delete_invalidates_item_cache(self, fake_cache, item_factory):
        from bot.web.admin import ItemValuesAdmin

        await item_factory(name="PanelDel", price=10, values=[("v1", False)])
        row = await self._stock_row("PanelDel")
        fake_cache.store["item_values:PanelDel"] = 1

        await self._fire(ItemValuesAdmin().after_model_delete, row, self._request())

        assert "item_values:PanelDel" not in fake_cache.store

    async def test_create_notifies_stock_subscribers(self, mock_bot, item_factory, user_factory):
        from bot.web.admin import ItemValuesAdmin, set_notifier_bot
        from bot.database.methods.create import subscribe_to_stock
        from bot.database.methods.read import is_subscribed_to_stock

        await user_factory(telegram_id=990001)
        await item_factory(name="PanelRestock", price=10, values=[("v1", False)])
        await subscribe_to_stock(990001, "PanelRestock")
        row = await self._stock_row("PanelRestock")

        set_notifier_bot(mock_bot)
        try:
            await self._fire(ItemValuesAdmin().after_model_change, {}, row, True, self._request())
        finally:
            set_notifier_bot(None)

        mock_bot.send_message.assert_awaited_once()
        assert mock_bot.send_message.await_args.kwargs["chat_id"] == 990001
        assert await is_subscribed_to_stock(990001, "PanelRestock") is False

    async def test_edit_does_not_notify(self, mock_bot, item_factory, user_factory):
        """Only new stock is an arrival; editing a value in place is not."""
        from bot.web.admin import ItemValuesAdmin, set_notifier_bot
        from bot.database.methods.create import subscribe_to_stock

        await user_factory(telegram_id=990002)
        await item_factory(name="PanelEdit", price=10, values=[("v1", False)])
        await subscribe_to_stock(990002, "PanelEdit")
        row = await self._stock_row("PanelEdit")

        set_notifier_bot(mock_bot)
        try:
            await self._fire(ItemValuesAdmin().after_model_change, {}, row, False, self._request())
        finally:
            set_notifier_bot(None)

        mock_bot.send_message.assert_not_awaited()

    async def test_no_bot_configured_is_a_noop(self, item_factory, user_factory):
        from bot.web.admin import ItemValuesAdmin, set_notifier_bot
        from bot.database.methods.create import subscribe_to_stock

        await user_factory(telegram_id=990003)
        await item_factory(name="PanelNoBot", price=10, values=[("v1", False)])
        await subscribe_to_stock(990003, "PanelNoBot")
        row = await self._stock_row("PanelNoBot")

        set_notifier_bot(None)
        # Must not raise even though someone is waiting.
        await self._fire(ItemValuesAdmin().after_model_change, {}, row, True, self._request())


class _FakeRedis:
    """Minimal async Redis stub with a toggleable outage for CacheManager tests."""

    def __init__(self):
        self.store = {}
        self.fail = False

    async def get(self, k):
        if self.fail:
            raise ConnectionError("down")
        return self.store.get(k)

    async def setex(self, k, ttl, v):
        if self.fail:
            raise ConnectionError("down")
        self.store[k] = v

    async def delete(self, *keys):
        if self.fail:
            raise ConnectionError("down")
        n = 0
        for k in keys:
            if k in self.store:
                del self.store[k]
                n += 1
        return n

    async def ping(self):
        if self.fail:
            raise ConnectionError("down")
        return True

    async def scan_iter(self, match=None, count=None):
        import fnmatch
        for k in list(self.store):
            if match is None or fnmatch.fnmatch(k, match):
                yield k


class TestDeferredInvalidationOnRedisOutage:
    async def test_deferred_delete_replays_on_recovery(self):
        from bot.misc.caching.cache import CacheManager
        r = _FakeRedis()
        r.store["user:1"] = b"stale"
        cm = CacheManager(r)

        r.fail = True  # outage begins
        assert await cm.delete("user:1") is False
        assert cm._healthy is False
        assert "user:1" in cm._pending_deletes
        assert "user:1" in r.store  # delete did not happen yet

        r.fail = False  # Redis recovers
        await cm.check_health()
        assert cm._healthy is True
        assert "user:1" not in r.store  # deferred delete replayed
        assert not cm._pending_deletes

    async def test_deferred_pattern_replays_on_recovery(self):
        from bot.misc.caching.cache import CacheManager
        r = _FakeRedis()
        r.store["category:A"] = b"x"
        r.store["category:B"] = b"y"
        cm = CacheManager(r)

        r.fail = True
        assert await cm.invalidate_pattern("category:*") == 0
        assert "category:*" in cm._pending_patterns

        r.fail = False
        await cm.check_health()
        assert "category:A" not in r.store and "category:B" not in r.store
        assert not cm._pending_patterns
