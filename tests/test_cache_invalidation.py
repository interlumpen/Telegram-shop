import asyncio
from decimal import Decimal
from unittest.mock import patch, AsyncMock, MagicMock

from sqlalchemy import select
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from bot.database.main import Database
from bot.database.methods.read import (
    invalidate_user_cache, invalidate_item_cache, invalidate_category_cache,
    invalidate_stats_cache, check_value_cached, async_cached, is_subscribed_to_stock,
)
from bot.database.methods.create import create_item, subscribe_to_stock
from bot.database.methods.lazy_queries import query_categories, query_items_in_category
from bot.database.methods.update import set_role, set_user_blocked, update_item
from bot.database.methods.transactions import admin_balance_change
from bot.database.methods.delete import delete_item, delete_category
from bot.database.methods.transactions import buy_item_transaction, \
    process_payment_with_referral
from bot.database.models.main import Goods, ItemValues
from bot.middleware.security import (
    AuthenticationMiddleware, set_auth_middleware, get_auth_middleware,
)
from bot.misc.caching.cache import CacheManager
from bot.web.admin import ItemValuesAdmin, set_notifier_bot


class TestCacheInvalidationFunctions:
    """Test that each invalidation function removes the expected keys."""

    async def test_invalidate_user_cache(self, fake_cache):
        fake_cache.store["user:123"] = {"telegram_id": 123, "balance": 0}
        fake_cache.store["auth:role:123"] = 1
        fake_cache.store["count:bought:123"] = 3
        fake_cache.store["count:ops:123"] = 7
        # A different user's entries must survive.
        fake_cache.store["user:124"] = {"telegram_id": 124}

        await invalidate_user_cache(123)

        assert "user:123" not in fake_cache.store
        assert "auth:role:123" not in fake_cache.store
        # The paginator counts are per-user and go stale on any purchase/topup.
        assert "count:bought:123" not in fake_cache.store
        assert "count:ops:123" not in fake_cache.store
        assert "user:124" in fake_cache.store

    async def test_invalidate_user_cache_takes_no_scan(self, fake_cache, monkeypatch):
        """This runs on every purchase/payment/checkout, so it must stay on
        targeted deletes — a pattern delete here is a Redis SCAN per write."""
        patterns = []

        async def _record(pattern):
            patterns.append(pattern)
            return 0

        monkeypatch.setattr(fake_cache, "invalidate_pattern", _record)

        await invalidate_user_cache(123)

        assert patterns == []

    async def test_invalidate_user_cache_drops_middleware_role_entry(self, fake_cache):
        import time as _time
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
        fake_cache.store["item_info:Test"] = {"name": "Test", "price": 100}
        fake_cache.store["item_values:Test"] = 5
        fake_cache.store["item_infinite:Test"] = True
        fake_cache.store["avg_rating:Test"] = 4.5
        fake_cache.store["category:Cat1"] = {"name": "Cat1"}

        await invalidate_item_cache("Test")

        assert "item_info:Test" not in fake_cache.store
        assert "item_values:Test" not in fake_cache.store
        assert "item_infinite:Test" not in fake_cache.store
        # Keyed by name, so a rename would otherwise strand the old average.
        assert "avg_rating:Test" not in fake_cache.store
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
        fake_cache.store["category_items:Cat:count"] = 3
        fake_cache.store["categories:count"] = 7
        # Another category's count must survive.
        fake_cache.store["category_items:Other:count"] = 1

        await invalidate_category_cache("Cat")

        assert "category:Cat" not in fake_cache.store
        assert "category_items:Cat:count" not in fake_cache.store
        assert "categories:count" not in fake_cache.store
        assert "category_items:Other:count" in fake_cache.store

    async def test_invalidate_category_cache_takes_no_scan(self, fake_cache, monkeypatch):
        """:count is the only key in the category_items namespace, so this runs
        on named deletes — a pattern would be a Redis SCAN per catalog edit."""
        patterns = []

        async def _record(pattern):
            patterns.append(pattern)
            return 0

        monkeypatch.setattr(fake_cache, "invalidate_pattern", _record)

        await invalidate_category_cache("Cat")

        assert patterns == []

    async def test_paginator_counts_are_cached_and_invalidated(self, fake_cache, category_factory):

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

    async def test_history_count_is_cached_across_page_turns(self, fake_cache, user_factory):
        """The operations history counts a UNION over three tables; the
        paginator asks for it on every page turn, so it must not re-run."""
        from sqlalchemy import event
        from bot.database.main import Database
        from bot.database.methods.lazy_queries import query_user_operations_history

        await user_factory(telegram_id=940100)

        assert await query_user_operations_history(940100, count_only=True) == 0
        assert "count:ops:940100" in fake_cache.store

        statements = []

        def _record(conn, cursor, statement, params, context, executemany):
            statements.append(statement)

        engine = Database().engine.sync_engine
        event.listen(engine, "before_cursor_execute", _record)
        try:
            for _ in range(5):
                await query_user_operations_history(940100, count_only=True)
        finally:
            event.remove(engine, "before_cursor_execute", _record)

        assert statements == []

    async def test_history_count_is_dropped_when_the_user_transacts(
        self, fake_cache, user_factory
    ):
        fake_cache.store["count:ops:940101"] = 4
        fake_cache.store["count:bought:940101"] = 2

        await invalidate_user_cache(940101)

        assert "count:ops:940101" not in fake_cache.store
        assert "count:bought:940101" not in fake_cache.store

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
        # stats:global is an all-time aggregate read only by the dashboard; it
        # rides its own 300s TTL rather than being recomputed after every write.
        assert fake_cache.store["stats:global"] == 100
        assert "user_count:" not in fake_cache.store
        assert "admin_count:" not in fake_cache.store
        # Targeted invalidation intentionally leaves stale dated keys to the
        # hourly scheduler sweep.
        assert "stats:daily:2000-01-01" in fake_cache.store

    async def test_async_cached_single_flight(self, fake_cache):

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

    async def test_balance_change_invalidates_cache(self, user_factory, fake_cache):
        from decimal import Decimal

        user = await user_factory(telegram_id=100001)
        user_id = user["telegram_id"]
        fake_cache.store[f"user:{user_id}"] = {"telegram_id": user_id, "balance": 0}

        ok, msg = await admin_balance_change(user_id, Decimal("500"))
        assert ok, msg
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
        fake_cache.store[f"item_info:{item_name}"] = {"name": item_name}

        await delete_item(item_name)
        await asyncio.sleep(0)

        assert f"item_info:{item_name}" not in fake_cache.store

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
        request = MagicMock()
        request.client.host = "127.0.0.1"
        return request

    async def _fire(self, method, *args):

        scheduled = []
        with patch('bot.web.admin.safe_create_task', side_effect=scheduled.append):
            await method(*args)
        for coro in scheduled:
            await coro

    async def _stock_row(self, item_name: str):

        async with Database().session() as s:
            item_id = (await s.execute(select(Goods.id).where(Goods.name == item_name))).scalar()
            return (await s.execute(
                select(ItemValues).where(ItemValues.item_id == item_id)
            )).scalars().first()

    async def test_create_invalidates_item_cache(self, fake_cache, item_factory):

        await item_factory(name="PanelItem", price=10, values=[("v1", False)])
        row = await self._stock_row("PanelItem")
        fake_cache.store["item_values:PanelItem"] = 0   # the stale "out of stock" read

        await self._fire(ItemValuesAdmin().after_model_change, {}, row, True, self._request())

        assert "item_values:PanelItem" not in fake_cache.store

    async def test_delete_invalidates_item_cache(self, fake_cache, item_factory):

        await item_factory(name="PanelDel", price=10, values=[("v1", False)])
        row = await self._stock_row("PanelDel")
        fake_cache.store["item_values:PanelDel"] = 1

        await self._fire(ItemValuesAdmin().after_model_delete, row, self._request())

        assert "item_values:PanelDel" not in fake_cache.store

    async def test_create_notifies_stock_subscribers(self, mock_bot, item_factory, user_factory):

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


class TestCacheManagerRedisDegradation:
    def _manager(self, exc):

        redis = MagicMock()
        redis.get = AsyncMock(side_effect=exc)
        redis.setex = AsyncMock(side_effect=exc)
        redis.delete = AsyncMock(side_effect=exc)
        redis.scan_iter = MagicMock(side_effect=exc)
        return CacheManager(redis)

    async def test_redis_connection_error_marks_unhealthy_on_get(self):

        mgr = self._manager(RedisConnectionError("connection lost"))
        assert await mgr.get("user:1") is None
        assert mgr._healthy is False

    async def test_redis_timeout_marks_unhealthy_on_set(self):

        mgr = self._manager(RedisTimeoutError("timed out"))
        assert await mgr.set("user:1", {"a": 1}) is False
        assert mgr._healthy is False

    async def test_delete_defers_invalidation_for_replay(self):

        mgr = self._manager(RedisConnectionError("connection lost"))
        assert await mgr.delete("item_info:Widget") is False
        # Deferred, not lost: a committed write must not keep serving stale data
        # once Redis comes back with the key's original TTL still running.
        assert "item_info:Widget" in mgr._pending_deletes

    async def test_pattern_invalidation_is_deferred_too(self):

        mgr = self._manager(RedisConnectionError("connection lost"))
        assert await mgr.invalidate_pattern("auth:role:*") == 0
        assert "auth:role:*" in mgr._pending_patterns

    def test_known_prefixes_cover_every_written_namespace(self):
        """The overflow path clears these wholesale; a namespace missing from the
        list would survive an outage as stale data."""

        for prefix in ("item_info:", "item_values:", "item_infinite:", "avg_rating:",
                       "category:", "category_items:", "user:", "auth:role:",
                       "user_count:", "admin_count:", "count:", "stats:"):
            assert prefix in CacheManager._KNOWN_PREFIXES


class TestRatingCacheInvalidation:

    async def test_item_rename_drops_the_old_average(self, item_factory, fake_cache):
        """avg_rating is keyed by product name, so a rename must clear it."""

        await item_factory(name="OldName", price=100, category="RateCat")
        fake_cache.store["avg_rating:OldName"] = 4.5
        fake_cache.store["item_info:OldName"] = {"name": "OldName"}

        ok, err = await update_item("OldName", "NewName", "desc", 100, "RateCat")
        await asyncio.sleep(0)

        assert (ok, err) == (True, None)
        assert "avg_rating:OldName" not in fake_cache.store


class TestCategoryMoveInvalidation:

    async def test_moving_an_item_invalidates_both_categories(
        self, item_factory, category_factory, fake_cache
    ):
        """Only the destination category used to be invalidated, leaving the
        source category's cached item list and count stale for up to 1800s."""

        await item_factory(name="Movable", price=100, category="FromCat")
        await category_factory("ToCat")

        fake_cache.store["category_items:FromCat:count"] = 1
        fake_cache.store["category_items:ToCat:count"] = 0

        ok, err = await update_item("Movable", "Movable", "desc", 100, "ToCat")
        await asyncio.sleep(0)

        assert (ok, err) == (True, None)
        assert "category_items:FromCat:count" not in fake_cache.store
        assert "category_items:ToCat:count" not in fake_cache.store


class TestNegativeRoleCaching:
    async def test_unknown_user_is_looked_up_once(self, monkeypatch):
        from bot.middleware.security import resolve_role_cached

        calls = 0

        async def counting_check_role(_user_id):
            nonlocal calls
            calls += 1
            return 0

        monkeypatch.setattr(
            "bot.database.methods.check_role", counting_check_role, raising=False,
        )

        l1 = {}
        assert await resolve_role_cached(999_000_001, l1) == 0
        assert await resolve_role_cached(999_000_001, l1) == 0
        assert calls == 1

    async def test_negative_entry_expires_sooner_than_a_real_role(self, monkeypatch):
        import time
        from bot.middleware.security import resolve_role_cached, NEGATIVE_ROLE_TTL

        calls = 0

        async def counting_check_role(_user_id):
            nonlocal calls
            calls += 1
            return 0

        monkeypatch.setattr(
            "bot.database.methods.check_role", counting_check_role, raising=False,
        )

        # Seed an entry that is still inside the full role TTL but past the
        # shorter negative one — a registration in between must be picked up.
        l1 = {999_000_002: (0, time.time() - NEGATIVE_ROLE_TTL - 1)}
        assert await resolve_role_cached(999_000_002, l1, ttl=600) == 0
        assert calls == 1
