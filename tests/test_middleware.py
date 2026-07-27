import math
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.types import CallbackQuery, Message

from bot.middleware.security import (
    check_suspicious_patterns, SecurityMiddleware, AuthenticationMiddleware,
    invalidate_auth_caches, set_auth_middleware, get_auth_middleware,
)
from bot.middleware.rate_limit import (
    RateLimiter, RateLimitConfig, RedisRateLimiter, RateLimitMiddleware,
    ALLOWED, BANNED, GLOBAL_EXCEEDED, ACTION_EXCEEDED,
)
from bot.main import _setup_rate_limiting
from bot.states import ShopStates


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

    @pytest.mark.parametrize("text,expected", [
        ("Hello, world!", False),
        ("", False),
        (None, False),
        ("shop", False),
        ("buy_item_123", False),
        ("profile", False),
        # SQL and shell metacharacters are the DB layer's problem, not this filter's - parameterized queries handle them, so they pass through.
        ("1 UNION SELECT * FROM users", False),
        ("1; DELETE FROM users", False),
        ("test | cat /etc/passwd", False),
        ("test `whoami`", False),
        ("../../etc/passwd", False),
        # XSS and oversized payloads are blocked.
        ("<script>alert(1)</script>", True),
        ("javascript:alert(1)", True),
        ("x" * 5000, True),
    ])
    def test_pattern_classification(self, text, expected):
        assert check_suspicious_patterns(text) is expected


class TestSecurityMiddlewareCriticalActions:

    def setup_method(self):
        self.middleware = SecurityMiddleware()

    @pytest.mark.parametrize("data,expected", [
        ("buy_item", True),
        ("pay_cryptopay", True),
        ("delete_category", True),
        ("admin_panel", True),
        ("role_mgmt", True),
        ("role_new", True),
        ("role_d_5", True),
        ("asr_2_123456", True),
        ("shop", False),
        ("profile", False),
        ("", False),
        (None, False),
    ])
    def test_critical_action(self, data, expected):
        assert self.middleware.is_critical_action(data) is expected

    @pytest.mark.parametrize("data,expected", [
        ("buy_item", True),
        ("pay_cryptopay", True),
        # Admin navigation is critical but idempotent — replaying it is harmless.
        ("role_mgmt", False),
        ("admin_panel", False),
        ("asr_2_123", False),
    ])
    def test_replay_protected(self, data, expected):
        assert self.middleware.is_replay_protected(data) is expected


class TestRateLimitActionMapping:
    def setup_method(self):
        self.mw = RateLimitMiddleware()

    def _action(self, data, state=None):
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
        message = MagicMock(spec=Message)
        message.text = "netflix"
        action = self.mw._get_action_from_event(
            message, {"raw_state": ShopStates.waiting_search_query.state}
        )
        assert action == "search"

    def test_plain_text_without_state_is_default(self):
        message = MagicMock(spec=Message)
        message.text = "netflix"
        assert self.mw._get_action_from_event(message, {"raw_state": None}) == "default"

    def test_every_mapped_action_has_a_limit(self):
        config = RateLimitConfig()
        for action in set(self.mw.action_mapping.values()):
            assert action in config.action_limits, f"{action!r} is mapped but unlimited"

    def test_startup_does_not_shadow_the_limits(self):
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

    async def pttl(self, key):
        self._boom()
        v = self.kv.get(key)
        if not v:
            return -2
        _, exp = v
        if exp is None:
            return -1
        return max(0, int((exp - time.time()) * 1000))

    def _allow_window(self, key, now, window, limit, member):
        """Trim the window, then record the request if it fits. True if allowed."""
        bucket = self.zsets.setdefault(key, {})
        for m, score in list(bucket.items()):
            if score <= now - window:
                del bucket[m]
        if len(bucket) >= limit:
            return False
        bucket[member] = now
        return True

    def register_script(self, source):
        """Emulate whichever of the two Lua scripts was registered.

        Told apart by arity: the combined per-update check passes three keys, the
        single-window helper one.
        """

        async def _run(keys, args):
            self._boom()
            if len(keys) == 1:
                now, window, limit, member = float(args[0]), float(args[1]), int(args[2]), args[3]
                return 1 if self._allow_window(keys[0], now, window, limit, member) else 0

            ban_key, g_key, a_key = keys
            now = float(args[0])
            g_window, g_limit = float(args[1]), int(args[2])
            a_window, a_limit = float(args[3]), int(args[4])
            member, ban_secs = args[5], int(args[6])
            has_action, bypass = int(args[7]), int(args[8])

            ban_ms = await self.pttl(ban_key)
            if ban_ms > 0:
                return [1, math.ceil(ban_ms / 1000)]

            if bypass == 1:
                return [0, 0]

            if not self._allow_window(g_key, now, g_window, g_limit, member):
                await self.set(ban_key, "1", ex=ban_secs)
                return [2, ban_secs]

            if has_action == 1:
                if not self._allow_window(a_key, now, a_window, a_limit, member):
                    oldest = await self.zrange(a_key, 0, 0, withscores=True)
                    wait = 0
                    if oldest:
                        wait = max(0, math.ceil(a_window - (now - oldest[0][1])))
                    return [3, wait]

            return [0, 0]

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


class TestCombinedCheck:
    """The single-round-trip check() must reach the same verdicts as the
    four separate calls it replaced, in the same order."""

    def setup_method(self):
        self.config = RateLimitConfig(
            global_limit=2, global_window=60,
            action_limits={"payment": (1, 60)}, ban_duration=300,
        )
        self.fallback = RateLimiter(self.config)

    def _limiter(self, fail=False):
        return RedisRateLimiter(self.config, _FakeRedis(fail=fail), self.fallback)

    async def test_allows_within_both_windows(self):
        r = self._limiter()
        assert await r.check(1, "default") == (ALLOWED, 0)

    async def test_global_overrun_bans_the_user(self):
        r = self._limiter()
        assert (await r.check(1, "default"))[0] == ALLOWED
        assert (await r.check(1, "default"))[0] == ALLOWED

        verdict, wait = await r.check(1, "default")
        assert verdict == GLOBAL_EXCEEDED
        assert wait == 300
        # The ban is applied in the same round-trip, so the next update is
        # rejected as banned rather than merely over the limit.
        verdict, wait = await r.check(1, "default")
        assert verdict == BANNED
        assert 0 < wait <= 300

    async def test_action_overrun_reports_wait_without_banning(self):
        r = self._limiter()
        assert (await r.check(2, "payment"))[0] == ALLOWED

        verdict, wait = await r.check(2, "payment")
        assert verdict == ACTION_EXCEEDED
        assert 0 < wait <= 60
        # An action overrun must not ban.
        assert await r.is_banned(2) is False

    async def test_action_overrun_still_counts_against_the_global_window(self):
        """Order is load-bearing: the global window is recorded before the
        action window is examined, exactly as the split calls did."""
        r = self._limiter()
        await r.check(3, "payment")   # 1st global, 1st action
        await r.check(3, "payment")   # 2nd global recorded, action rejected

        verdict, _wait = await r.check(3, "default")
        assert verdict == GLOBAL_EXCEEDED

    async def test_bypass_skips_windows_but_not_the_ban(self):
        r = self._limiter()
        for _ in range(5):
            assert await r.check(4, "payment", bypass=True) == (ALLOWED, 0)

        await r.ban_user(4)
        verdict, wait = await r.check(4, "payment", bypass=True)
        assert verdict == BANNED
        assert 0 < wait <= 300

    async def test_unknown_action_only_uses_the_global_window(self):
        r = self._limiter()
        assert (await r.check(5, "unknown"))[0] == ALLOWED
        assert (await r.check(5, "unknown"))[0] == ALLOWED
        assert (await r.check(5, "unknown"))[0] == GLOBAL_EXCEEDED

    async def test_falls_back_to_memory_on_redis_error(self):
        r = self._limiter(fail=True)
        assert await r.check(6, "default") == (ALLOWED, 0)
        assert 6 in self.fallback.user_requests

    async def test_in_memory_check_matches_the_redis_verdicts(self):
        limiter = RateLimiter(self.config)
        assert limiter.check(7, "payment") == (ALLOWED, 0)

        verdict, wait = limiter.check(7, "payment")
        assert verdict == ACTION_EXCEEDED
        assert 0 < wait <= 60

        assert limiter.check(7, "default")[0] == GLOBAL_EXCEEDED
        assert limiter.is_banned(7) is True
        assert limiter.check(7, "default")[0] == BANNED

    def test_in_memory_bypass_skips_windows_but_not_the_ban(self):
        limiter = RateLimiter(self.config)
        for _ in range(5):
            assert limiter.check(8, "payment", bypass=True) == (ALLOWED, 0)

        limiter.ban_user(8)
        assert limiter.check(8, "payment", bypass=True)[0] == BANNED


class TestRoleCacheRedis:

    async def test_read_through_and_write_through(self, user_factory, fake_cache):
        fake_cache._healthy = True
        await user_factory(telegram_id=210001)  # default USER role, perms == 1
        auth = AuthenticationMiddleware()

        assert await auth.get_user_role_cached(210001) == 1
        # Written through to the shared cache...
        assert "auth:role:210001" in fake_cache.store
        # ...and to the in-process tier, which is checked first: a stale Redis
        # value must not be re-read while the local entry is live.
        assert 210001 in auth.admin_cache
        fake_cache.store["auth:role:210001"] = 999
        assert await auth.get_user_role_cached(210001) == 1

        # Dropping the local entry (what every invalidation path does) falls
        # through to Redis rather than to the DB, and repopulates the L1 tier.
        auth.admin_cache.pop(210001)
        assert await auth.get_user_role_cached(210001) == 999
        assert auth.admin_cache[210001][0] == 999

    async def test_falls_back_to_memory_when_cache_unhealthy(self, user_factory, fake_cache):
        fake_cache._healthy = False
        await user_factory(telegram_id=210002)
        auth = AuthenticationMiddleware()

        assert await auth.get_user_role_cached(210002) == 1
        assert 210002 in auth.admin_cache
        assert "auth:role:210002" not in fake_cache.store


class TestSecurityMiddlewareWithoutFromUser:
    async def test_suspicious_text_without_from_user_does_not_crash(self):
        mw = SecurityMiddleware()

        event = MagicMock(spec=Message)
        event.from_user = None
        event.text = "<script>alert(1)</script>"

        handler = AsyncMock(return_value="passed")
        # Suspicious messages are logged, not blocked — the handler still runs.
        assert await mw(handler, event, {}) == "passed"

    async def test_benign_text_without_from_user_passes(self):
        mw = SecurityMiddleware()

        event = MagicMock(spec=Message)
        event.from_user = None
        event.text = "hello"

        handler = AsyncMock(return_value="passed")
        assert await mw(handler, event, {}) == "passed"
