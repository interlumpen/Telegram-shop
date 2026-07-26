import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.types import CallbackQuery, Message

from bot.middleware.security import (
    check_suspicious_patterns, SecurityMiddleware, AuthenticationMiddleware,
    invalidate_auth_caches, set_auth_middleware, get_auth_middleware,
)
from bot.middleware.rate_limit import RateLimiter, RateLimitConfig, RedisRateLimiter


def _auth_callback(user_id: int, data: str = "profile") -> AsyncMock:
    """A CallbackQuery mock that passes the middleware's isinstance checks."""
    call = AsyncMock(spec=CallbackQuery)
    call.data = data
    call.from_user = MagicMock()
    call.from_user.id = user_id
    call.from_user.is_bot = False
    call.answer = AsyncMock()
    return call


class TestSuspiciousPatterns:

    def test_safe_input(self):
        assert check_suspicious_patterns("Hello, world!") is False

    def test_empty_string(self):
        assert check_suspicious_patterns("") is False

    def test_none(self):
        assert check_suspicious_patterns(None) is False

    def test_sql_patterns_not_blocked(self):
        assert check_suspicious_patterns("1 UNION SELECT * FROM users") is False
        assert check_suspicious_patterns("1; DELETE FROM users") is False

    def test_xss_script_tag(self):
        assert check_suspicious_patterns("<script>alert(1)</script>") is True

    def test_xss_javascript_protocol(self):
        assert check_suspicious_patterns("javascript:alert(1)") is True

    def test_shell_patterns_not_blocked(self):
        assert check_suspicious_patterns("test | cat /etc/passwd") is False
        assert check_suspicious_patterns("test `whoami`") is False

    def test_path_traversal_not_blocked(self):
        assert check_suspicious_patterns("../../etc/passwd") is False

    def test_long_string(self):
        assert check_suspicious_patterns("x" * 5000) is True

    def test_normal_callback_data(self):
        assert check_suspicious_patterns("shop") is False
        assert check_suspicious_patterns("buy_item_123") is False
        assert check_suspicious_patterns("profile") is False


class TestSecurityMiddlewareCriticalActions:

    def setup_method(self):
        self.middleware = SecurityMiddleware()

    def test_buy_is_critical(self):
        assert self.middleware.is_critical_action("buy_item") is True

    def test_pay_is_critical(self):
        assert self.middleware.is_critical_action("pay_cryptopay") is True

    def test_delete_is_critical(self):
        assert self.middleware.is_critical_action("delete_category") is True

    def test_admin_is_critical(self):
        assert self.middleware.is_critical_action("admin_panel") is True

    def test_shop_is_not_critical(self):
        assert self.middleware.is_critical_action("shop") is False

    def test_profile_is_not_critical(self):
        assert self.middleware.is_critical_action("profile") is False

    def test_role_mgmt_is_critical(self):
        assert self.middleware.is_critical_action("role_mgmt") is True

    def test_role_new_is_critical(self):
        assert self.middleware.is_critical_action("role_new") is True

    def test_role_delete_is_critical(self):
        assert self.middleware.is_critical_action("role_d_5") is True

    def test_asr_is_critical(self):
        assert self.middleware.is_critical_action("asr_2_123456") is True

    def test_empty_string(self):
        assert self.middleware.is_critical_action("") is False

    def test_none(self):
        assert self.middleware.is_critical_action(None) is False

    def test_buy_is_replay_protected(self):
        assert self.middleware.is_replay_protected("buy_item") is True

    def test_pay_is_replay_protected(self):
        assert self.middleware.is_replay_protected("pay_cryptopay") is True

    def test_role_mgmt_not_replay_protected(self):
        assert self.middleware.is_replay_protected("role_mgmt") is False

    def test_admin_not_replay_protected(self):
        assert self.middleware.is_replay_protected("admin_panel") is False

    def test_asr_not_replay_protected(self):
        assert self.middleware.is_replay_protected("asr_2_123") is False


class TestRateLimitActionMapping:
    def setup_method(self):
        from bot.middleware.rate_limit import RateLimitMiddleware
        self.mw = RateLimitMiddleware()

    def _action(self, data, state=None):
        from unittest.mock import MagicMock
        from aiogram.types import CallbackQuery
        call = MagicMock(spec=CallbackQuery)
        call.data = data
        return self.mw._get_action_from_event(call, {"raw_state": state})

    @pytest.mark.parametrize("data", ["cat:1:0", "itm:2:0", "sitm:0:0",
                                      "categories-page_2", "gp_1", "shop"])
    def test_browsing_is_shop_view(self, data):
        assert self._action(data) == "shop_view"

    @pytest.mark.parametrize("data", ["buy_item", "add_to_cart", "cart_checkout_confirm"])
    def test_purchase_paths_are_buy_item(self, data):
        assert self._action(data) == "buy_item"

    def test_shop_search_is_search_not_shop_view(self):
        assert self._action("shop_search") == "search"

    def test_search_result_navigation_is_not_billed_as_a_search(self):
        assert self._action("sp_2") == "shop_view"
        assert self._action("sp_2") == self._action("gp_2")

    def test_top_up_and_payment(self):
        assert self._action("replenish_balance") == "top_up"
        assert self._action("pay_stars") == "payment"

    def test_unknown_callback_is_default(self):
        assert self._action("something_else") == "default"

    def test_search_text_input_recognised_by_state(self):
        from unittest.mock import MagicMock
        from aiogram.types import Message
        from bot.states import ShopStates

        message = MagicMock(spec=Message)
        message.text = "netflix"
        action = self.mw._get_action_from_event(
            message, {"raw_state": ShopStates.waiting_search_query.state}
        )
        assert action == "search"

    def test_plain_text_without_state_is_default(self):
        from unittest.mock import MagicMock
        from aiogram.types import Message

        message = MagicMock(spec=Message)
        message.text = "netflix"
        assert self.mw._get_action_from_event(message, {"raw_state": None}) == "default"

    def test_every_mapped_action_has_a_limit(self):
        config = RateLimitConfig()
        for action in set(self.mw.action_mapping.values()):
            assert action in config.action_limits, f"{action!r} is mapped but unlimited"

    def test_startup_does_not_shadow_the_limits(self):
        from unittest.mock import MagicMock, patch
        from bot.main import _setup_rate_limiting

        with patch('bot.main.setup_rate_limiting') as setup:
            _setup_rate_limiting(MagicMock(), auth_middleware=MagicMock())

        passed_config = setup.call_args[0][1]
        assert passed_config.action_limits == RateLimitConfig().action_limits


class TestRateLimiter:

    def setup_method(self):
        self.config = RateLimitConfig(
            global_limit=5,
            global_window=60,
            action_limits={"payment": (2, 60)},
            ban_duration=300,
        )
        self.limiter = RateLimiter(self.config)

    def test_global_limit_allows_within_limit(self):
        for _ in range(5):
            assert self.limiter.check_global_limit(1) is True

    def test_global_limit_blocks_over_limit(self):
        for _ in range(5):
            self.limiter.check_global_limit(1)
        assert self.limiter.check_global_limit(1) is False

    def test_global_limit_per_user(self):
        for _ in range(5):
            self.limiter.check_global_limit(1)
        # Different user should still be allowed
        assert self.limiter.check_global_limit(2) is True

    def test_action_limit_allows_within_limit(self):
        assert self.limiter.check_action_limit(1, "payment") is True
        assert self.limiter.check_action_limit(1, "payment") is True

    def test_action_limit_blocks_over_limit(self):
        self.limiter.check_action_limit(1, "payment")
        self.limiter.check_action_limit(1, "payment")
        assert self.limiter.check_action_limit(1, "payment") is False

    def test_unknown_action_always_passes(self):
        for _ in range(100):
            assert self.limiter.check_action_limit(1, "unknown_action") is True

    def test_ban_user(self):
        self.limiter.ban_user(1)
        assert self.limiter.is_banned(1) is True

    def test_not_banned_by_default(self):
        assert self.limiter.is_banned(1) is False

    def test_ban_expires(self):
        self.limiter.ban_user(1)
        # Manually set ban time in the past
        self.limiter.banned_users[1] = time.time() - 400
        assert self.limiter.is_banned(1) is False

    def test_get_wait_time_not_limited(self):
        assert self.limiter.get_wait_time(1) == 0

    def test_get_wait_time_banned(self):
        self.limiter.ban_user(1)
        wait = self.limiter.get_wait_time(1)
        assert 0 < wait <= 300


class TestAuthenticationMiddleware:

    def setup_method(self):
        self.auth = AuthenticationMiddleware()

    async def test_block_user(self, user_factory):
        await user_factory(telegram_id=200001)
        result = await self.auth.block_user(200001)
        assert result is True
        assert 200001 in self.auth.blocked_users

    async def test_unblock_user(self, user_factory):
        await user_factory(telegram_id=200002)
        await self.auth.block_user(200002)
        result = await self.auth.unblock_user(200002)
        assert result is True
        assert 200002 not in self.auth.blocked_users

    async def test_block_nonexistent_user(self):
        result = await self.auth.block_user(999999999)
        assert result is False

    async def test_blocked_check_served_from_memory(self, monkeypatch):
        self.auth._blocked_loaded = True
        self.auth.blocked_users.add(300001)
        db_check = AsyncMock(return_value=False)
        monkeypatch.setattr('bot.database.methods.is_user_blocked', db_check)

        handler = AsyncMock()
        call = _auth_callback(300001)
        result = await self.auth(handler, call, {})

        assert result is None
        handler.assert_not_awaited()
        call.answer.assert_awaited_once()
        db_check.assert_not_awaited()

    async def test_unblocked_user_passes_without_db_query(self, monkeypatch, user_factory):
        await user_factory(telegram_id=300002)
        self.auth._blocked_loaded = True
        db_check = AsyncMock(return_value=False)
        monkeypatch.setattr('bot.database.methods.is_user_blocked', db_check)

        handler = AsyncMock()
        await self.auth(handler, _auth_callback(300002), {})

        handler.assert_awaited_once()
        db_check.assert_not_awaited()

    async def test_failed_startup_load_recovers_lazily(self, user_factory):
        await user_factory(telegram_id=300003)
        await self.auth.block_user(300003)
        # Simulate a failed startup load: empty set, flag down.
        self.auth._blocked_loaded = False
        self.auth.blocked_users = set()

        handler = AsyncMock()
        result = await self.auth(handler, _auth_callback(300003), {})

        assert result is None
        handler.assert_not_awaited()
        assert self.auth._blocked_loaded is True
        assert 300003 in self.auth.blocked_users

    async def test_invalidate_auth_caches_syncs_blocked_set(self):
        prev = get_auth_middleware()
        set_auth_middleware(self.auth)
        try:
            invalidate_auth_caches(300004, blocked=True)
            assert 300004 in self.auth.blocked_users
            invalidate_auth_caches(300004, blocked=False)
            assert 300004 not in self.auth.blocked_users
            # Role-only invalidation must not unblock.
            self.auth.blocked_users.add(300005)
            invalidate_auth_caches(300005)
            assert 300005 in self.auth.blocked_users
        finally:
            set_auth_middleware(prev)


class _FakeRedis:
    def __init__(self, fail: bool = False):
        self.zsets: dict = {}
        self.kv: dict = {}
        self.fail = fail

    def _boom(self):
        if self.fail:
            raise ConnectionError("redis down")

    async def zremrangebyscore(self, key, mn, mx):
        self._boom()
        z = self.zsets.get(key, {})
        for m in [m for m, s in z.items() if mn <= s <= mx]:
            del z[m]
        self.zsets[key] = z

    async def zcard(self, key):
        self._boom()
        return len(self.zsets.get(key, {}))

    async def zadd(self, key, mapping):
        self._boom()
        self.zsets.setdefault(key, {}).update(mapping)

    async def zrange(self, key, start, end, withscores=False):
        self._boom()
        items = sorted(self.zsets.get(key, {}).items(), key=lambda kv: kv[1])
        end = len(items) - 1 if end == -1 else end
        sel = items[start:end + 1]
        return [(m, s) for m, s in sel] if withscores else [m for m, s in sel]

    async def pexpire(self, key, ms):
        self._boom()
        return True

    async def set(self, key, value, ex=None):
        self._boom()
        self.kv[key] = (value, (time.time() + ex) if ex else None)

    async def exists(self, key):
        self._boom()
        v = self.kv.get(key)
        if not v:
            return 0
        _, exp = v
        if exp is not None and time.time() > exp:
            del self.kv[key]
            return 0
        return 1

    async def ttl(self, key):
        self._boom()
        v = self.kv.get(key)
        if not v:
            return -2
        _, exp = v
        return -1 if exp is None else max(0, int(exp - time.time()))

    async def delete(self, key):
        self.zsets.pop(key, None)
        self.kv.pop(key, None)

    def register_script(self, _source):
        async def _run(keys, args):
            self._boom()
            key = keys[0]
            now, window, limit, member = float(args[0]), float(args[1]), int(args[2]), args[3]
            bucket = self.zsets.setdefault(key, {})
            for m, score in list(bucket.items()):
                if score <= now - window:
                    del bucket[m]
            if len(bucket) >= limit:
                return 0
            bucket[member] = now
            return 1

        return _run


class TestRedisRateLimiter:

    def setup_method(self):
        self.config = RateLimitConfig(
            global_limit=2, global_window=60,
            action_limits={"payment": (1, 60)}, ban_duration=300,
        )
        self.fallback = RateLimiter(self.config)

    def _limiter(self, fail=False):
        return RedisRateLimiter(self.config, _FakeRedis(fail=fail), self.fallback)

    async def test_global_limit_allows_then_blocks(self):
        r = self._limiter()
        assert await r.check_global_limit(1) is True
        assert await r.check_global_limit(1) is True
        assert await r.check_global_limit(1) is False

    async def test_global_limit_is_per_user(self):
        r = self._limiter()
        await r.check_global_limit(1)
        await r.check_global_limit(1)
        assert await r.check_global_limit(2) is True

    async def test_action_limit_blocks_over_limit(self):
        r = self._limiter()
        assert await r.check_action_limit(1, "payment") is True
        assert await r.check_action_limit(1, "payment") is False

    async def test_unknown_action_always_passes(self):
        r = self._limiter()
        for _ in range(10):
            assert await r.check_action_limit(1, "unknown") is True

    async def test_ban_sets_and_reports(self):
        r = self._limiter()
        assert await r.is_banned(1) is False
        await r.ban_user(1)
        assert await r.is_banned(1) is True
        wait = await r.get_wait_time(1)
        assert 0 < wait <= 300

    async def test_falls_back_to_memory_on_redis_error(self):
        r = self._limiter(fail=True)
        # Redis raises -> in-memory fallback answers (allowed within its limit).
        assert await r.check_global_limit(5) is True
        assert 5 in self.fallback.user_requests


class TestRoleCacheRedis:

    async def test_read_through_and_write_through(self, user_factory, fake_cache):
        fake_cache._healthy = True
        await user_factory(telegram_id=210001)  # default USER role, perms == 1
        auth = AuthenticationMiddleware()

        assert await auth.get_user_role_cached(210001) == 1
        # Written through to the shared cache...
        assert "auth:role:210001" in fake_cache.store
        # ...and read from it first: overwrite Redis and expect the new value,
        # even though the in-memory admin_cache still holds the old one.
        fake_cache.store["auth:role:210001"] = 999
        assert await auth.get_user_role_cached(210001) == 999

    async def test_falls_back_to_memory_when_cache_unhealthy(self, user_factory, fake_cache):
        fake_cache._healthy = False
        await user_factory(telegram_id=210002)
        auth = AuthenticationMiddleware()

        assert await auth.get_user_role_cached(210002) == 1
        assert 210002 in auth.admin_cache
        assert "auth:role:210002" not in fake_cache.store


class TestPermissionHasAnyAdminPerm:

    def test_use_only_is_not_admin(self):
        from bot.database.models import Permission
        assert Permission.has_any_admin_perm(1) is False

    def test_admin_perms_is_admin(self):
        from bot.database.models import Permission
        assert Permission.has_any_admin_perm(31) is True

    def test_single_admin_bit_is_admin(self):
        from bot.database.models import Permission
        assert Permission.has_any_admin_perm(2) is True  # BROADCAST only

    def test_zero_is_not_admin(self):
        from bot.database.models import Permission
        assert Permission.has_any_admin_perm(0) is False


class TestSecurityMiddlewareWithoutFromUser:
    async def test_suspicious_text_without_from_user_does_not_crash(self):
        from bot.middleware.security import SecurityMiddleware

        mw = SecurityMiddleware()

        event = MagicMock(spec=Message)
        event.from_user = None
        event.text = "<script>alert(1)</script>"

        handler = AsyncMock(return_value="passed")
        # Suspicious messages are logged, not blocked — the handler still runs.
        assert await mw(handler, event, {}) == "passed"

    async def test_benign_text_without_from_user_passes(self):
        from bot.middleware.security import SecurityMiddleware

        mw = SecurityMiddleware()

        event = MagicMock(spec=Message)
        event.from_user = None
        event.text = "hello"

        handler = AsyncMock(return_value="passed")
        assert await mw(handler, event, {}) == "passed"
