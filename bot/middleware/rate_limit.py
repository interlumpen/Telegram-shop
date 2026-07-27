import logging
import time
from typing import Dict, Any, Callable, Awaitable
from collections import defaultdict
from dataclasses import dataclass, field
from uuid import uuid4

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, TelegramObject
from aiogram.exceptions import TelegramBadRequest

from bot.i18n import localize
from bot.database.models import Permission
from bot.states import ShopStates

logger = logging.getLogger(__name__)


@dataclass
class RateLimitConfig:
    """Configuration for rate limiting"""
    # Global limits
    global_limit: int = 30  # requests
    global_window: int = 60  # seconds

    # Limits for specific actions — (requests, window_seconds).
    action_limits: dict = field(default_factory=lambda: {
        'payment': (10, 60),  # 10 times a minute
        'shop_view': (60, 60),  # 60 times per minute — browsing and paging
        'buy_item': (5, 60),  # 5 purchases a minute
        'search': (10, 60),  # 10 new searches a minute — each is a LIKE scan
        'top_up': (5, 300),  # 5 top-ups in 5 minutes
        'command': (20, 60),  # 20 slash commands a minute (admins bypass)
    })

    # Temporary ban after exceeding
    ban_duration: int = 300  # 5 minutes

    # Exceptions for admins
    admin_bypass: bool = True


class RateLimiter:
    """A repository for tracking rate limits"""

    def __init__(self, config: RateLimitConfig):
        self.config = config
        self.user_requests: Dict[int, list] = defaultdict(list)
        self.user_actions: Dict[str, Dict[int, list]] = defaultdict(lambda: defaultdict(list))
        self.banned_users: Dict[int, float] = {}

    def _clean_old_requests(self, requests: list, window: int) -> list:
        """Clears old requests outside the window"""
        current_time = time.time()
        return [req_time for req_time in requests if current_time - req_time < window]

    def is_banned(self, user_id: int) -> bool:
        """Checks if the user is banned"""
        if user_id not in self.banned_users:
            return False

        ban_time = self.banned_users[user_id]
        if time.time() - ban_time > self.config.ban_duration:
            del self.banned_users[user_id]
            return False

        return True

    def ban_user(self, user_id: int):
        """Bans the user for a period of time"""
        self.banned_users[user_id] = time.time()

    def check_global_limit(self, user_id: int) -> bool:
        """Checks the global request limit"""
        current_time = time.time()

        # Clearing old requests
        self.user_requests[user_id] = self._clean_old_requests(
            self.user_requests[user_id],
            self.config.global_window
        )

        # Remove empty key to prevent memory leak
        if not self.user_requests[user_id]:
            del self.user_requests[user_id]

        # Checking the limit
        if len(self.user_requests.get(user_id, [])) >= self.config.global_limit:
            return False

        # Add the current query
        self.user_requests[user_id].append(current_time)
        return True

    def check_action_limit(self, user_id: int, action: str) -> bool:
        """Checks the limit for a specific action"""
        if action not in self.config.action_limits:
            return True

        limit, window = self.config.action_limits[action]
        current_time = time.time()

        # Clear old requests for this action
        self.user_actions[action][user_id] = self._clean_old_requests(
            self.user_actions[action][user_id],
            window
        )

        # Remove empty keys to prevent memory leak
        if not self.user_actions[action][user_id]:
            del self.user_actions[action][user_id]
            if not self.user_actions[action]:
                del self.user_actions[action]

        # Checking the limit
        action_requests = self.user_actions.get(action, {}).get(user_id, [])
        if len(action_requests) >= limit:
            return False

        # Add the current query
        self.user_actions[action][user_id].append(current_time)
        return True

    def check(self, user_id: int, action: str, bypass: bool = False) -> tuple[int, int]:
        """In-memory counterpart of RedisRateLimiter.check."""
        if self.is_banned(user_id):
            return BANNED, self.get_wait_time(user_id)

        if bypass:
            return ALLOWED, 0

        if not self.check_global_limit(user_id):
            self.ban_user(user_id)
            return GLOBAL_EXCEEDED, self.config.ban_duration

        if not self.check_action_limit(user_id, action):
            return ACTION_EXCEEDED, self.get_wait_time(user_id, action)

        return ALLOWED, 0

    def get_wait_time(self, user_id: int, action: str = None) -> int:
        """Returns the wait time until the next available request"""
        if self.is_banned(user_id):
            ban_time = self.banned_users[user_id]
            return int(self.config.ban_duration - (time.time() - ban_time))

        if action and action in self.config.action_limits:
            limit, window = self.config.action_limits[action]
            requests = self.user_actions.get(action, {}).get(user_id, [])
            if len(requests) >= limit:
                oldest_request = min(requests)
                return int(window - (time.time() - oldest_request))

        # Global limit
        global_reqs = self.user_requests.get(user_id, [])
        if len(global_reqs) >= self.config.global_limit:
            oldest_request = min(global_reqs)
            return int(self.config.global_window - (time.time() - oldest_request))

        return 0


# Verdicts returned by RedisRateLimiter.check / RateLimiter.check.
ALLOWED = 0
BANNED = 1
GLOBAL_EXCEEDED = 2
ACTION_EXCEEDED = 3


class RedisRateLimiter:
    """Distributed rate limiter backed by Redis (shared across processes).

    Uses one sorted set per (scope, user) as a sliding window of request
    timestamps, and a TTL key for temporary bans. On any Redis error every
    method transparently delegates to the in-memory fallback limiter, so the
    bot never fails closed when Redis is unavailable.
    """

    # Trim the window, check the count and record the request in a single round-trip.
    # Split across separate commands, two concurrent updates from one user could both pass the check before either recorded itself,
    # letting the limit be exceeded — and it cost four round-trips per update.
    _ALLOW_LUA = """
    local key    = KEYS[1]
    local now    = tonumber(ARGV[1])
    local window = tonumber(ARGV[2])
    local limit  = tonumber(ARGV[3])
    local member = ARGV[4]
    redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
    if redis.call('ZCARD', key) >= limit then
        return 0
    end
    redis.call('ZADD', key, now, member)
    redis.call('PEXPIRE', key, math.floor(window * 1000))
    return 1
    """

    # The whole per-update decision in one round-trip: ban check, both sliding windows, the auto-ban on a global overrun and the bookkeeping.

    # Order matters and mirrors the split version exactly: the ban is checked before the admin bypass applies,
    # and the global window is checked *and recorded* before the action window is looked at, so a request rejected by
    # an action limit still counts against the global budget. An admin (bypass=1) is only ban-checked — their traffic never touches the windows.
    _CHECK_LUA = """
    local ban_key  = KEYS[1]
    local g_key    = KEYS[2]
    local a_key    = KEYS[3]
    local now      = tonumber(ARGV[1])
    local g_window = tonumber(ARGV[2])
    local g_limit  = tonumber(ARGV[3])
    local a_window = tonumber(ARGV[4])
    local a_limit  = tonumber(ARGV[5])
    local member   = ARGV[6]
    local ban_secs = tonumber(ARGV[7])
    local has_act  = tonumber(ARGV[8])
    local bypass   = tonumber(ARGV[9])

    local ban_ms = redis.call('PTTL', ban_key)
    if ban_ms > 0 then
        return {1, math.ceil(ban_ms / 1000)}
    end

    if bypass == 1 then
        return {0, 0}
    end

    redis.call('ZREMRANGEBYSCORE', g_key, 0, now - g_window)
    if redis.call('ZCARD', g_key) >= g_limit then
        redis.call('SET', ban_key, '1', 'PX', ban_secs * 1000)
        return {2, ban_secs}
    end
    redis.call('ZADD', g_key, now, member)
    redis.call('PEXPIRE', g_key, math.floor(g_window * 1000))

    if has_act == 1 then
        redis.call('ZREMRANGEBYSCORE', a_key, 0, now - a_window)
        if redis.call('ZCARD', a_key) >= a_limit then
            local oldest = redis.call('ZRANGE', a_key, 0, 0, 'WITHSCORES')
            local wait = 0
            if oldest[2] then
                wait = math.ceil(a_window - (now - tonumber(oldest[2])))
                if wait < 0 then wait = 0 end
            end
            return {3, wait}
        end
        redis.call('ZADD', a_key, now, member)
        redis.call('PEXPIRE', a_key, math.floor(a_window * 1000))
    end

    return {0, 0}
    """

    def __init__(self, config: RateLimitConfig, redis, fallback: "RateLimiter"):
        self.config = config
        self.redis = redis
        self.fallback = fallback
        # register_script caches by SHA and falls back to EVAL on NOSCRIPT.
        self._allow_script = redis.register_script(self._ALLOW_LUA)
        self._check_script = redis.register_script(self._CHECK_LUA)

    @staticmethod
    def _member() -> str:
        # Unique per request so identical-timestamp entries don't collapse.
        return f"{time.time():.6f}:{uuid4().hex}"

    async def _allow(self, key: str, window: int, limit: int) -> bool:
        now = time.time()
        allowed = await self._allow_script(
            keys=[key], args=[now, window, limit, self._member()],
        )
        return bool(allowed)

    async def is_banned(self, user_id: int) -> bool:
        try:
            return bool(await self.redis.exists(f"rl:ban:{user_id}"))
        except Exception:
            return self.fallback.is_banned(user_id)

    async def ban_user(self, user_id: int) -> None:
        try:
            await self.redis.set(f"rl:ban:{user_id}", "1", ex=self.config.ban_duration)
        except Exception:
            self.fallback.ban_user(user_id)

    async def check_global_limit(self, user_id: int) -> bool:
        try:
            return await self._allow(f"rl:g:{user_id}", self.config.global_window, self.config.global_limit)
        except Exception:
            return self.fallback.check_global_limit(user_id)

    async def check_action_limit(self, user_id: int, action: str) -> bool:
        if action not in self.config.action_limits:
            return True
        limit, window = self.config.action_limits[action]
        try:
            return await self._allow(f"rl:a:{action}:{user_id}", window, limit)
        except Exception:
            return self.fallback.check_action_limit(user_id, action)

    async def check(self, user_id: int, action: str, bypass: bool = False) -> tuple[int, int]:
        """Run the whole rate-limit decision in one round-trip.

        Returns ``(verdict, wait_seconds)`` where verdict is one of ALLOWED /
        BANNED / GLOBAL_EXCEEDED / ACTION_EXCEEDED. ``bypass`` marks an admin:
        the ban still applies, the windows do not. Falls back to the in-memory
        limiter on any Redis error, exactly like the individual checks do.
        """
        limit, window = self.config.action_limits.get(action, (0, 0))
        has_action = 1 if action in self.config.action_limits else 0
        try:
            verdict, wait = await self._check_script(
                keys=[
                    f"rl:ban:{user_id}",
                    f"rl:g:{user_id}",
                    f"rl:a:{action}:{user_id}",
                ],
                args=[
                    time.time(),
                    self.config.global_window, self.config.global_limit,
                    window, limit,
                    self._member(),
                    self.config.ban_duration,
                    has_action,
                    1 if bypass else 0,
                ],
            )
            return int(verdict), int(wait)
        except Exception:
            return self.fallback.check(user_id, action, bypass)

    async def get_wait_time(self, user_id: int, action: str = None) -> int:
        try:
            ban_ttl = await self.redis.ttl(f"rl:ban:{user_id}")
            if ban_ttl and ban_ttl > 0:
                return int(ban_ttl)

            now = time.time()
            if action and action in self.config.action_limits:
                _limit, window = self.config.action_limits[action]
                key = f"rl:a:{action}:{user_id}"
            else:
                window = self.config.global_window
                key = f"rl:g:{user_id}"

            oldest = await self.redis.zrange(key, 0, 0, withscores=True)
            if oldest:
                _member, score = oldest[0]
                return max(0, int(window - (now - score)))
            return 0
        except Exception:
            return self.fallback.get_wait_time(user_id, action)


class RateLimitMiddleware(BaseMiddleware):
    """Middleware to limit the frequency of requests"""

    def __init__(self, config: RateLimitConfig = None, auth_middleware=None):
        self.config = config or RateLimitConfig()
        self.limiter = RateLimiter(self.config)
        self._redis_limiter: "RedisRateLimiter | None" = None
        self.auth_middleware = auth_middleware
        self.action_mapping = {
            'replenish_balance': 'top_up',
            'pay_': 'payment',
            'cart_checkout_confirm': 'buy_item',
            'add_to_cart': 'buy_item',
            'buy_item': 'buy_item',
            'shop_search': 'search',
            'shop': 'shop_view',
            'cat:': 'shop_view',
            'itm:': 'shop_view',
            'sitm:': 'shop_view',
            'categories-page_': 'shop_view',
            'gp_': 'shop_view',
            'sp_': 'shop_view',
            'bought-item:': 'shop_view',
            'bought-goods-page_': 'shop_view',
            'earning_detail:': 'shop_view',
            'check': 'shop_view',
        }

    def _get_action_from_event(self, event: TelegramObject, data: Dict[str, Any] | None = None) -> str:
        """Determines the action from the event"""
        if isinstance(event, CallbackQuery):
            cb_data = event.data or ""
            for prefix, action in self.action_mapping.items():
                if cb_data.startswith(prefix):
                    return action

        elif isinstance(event, Message):
            if data is not None and data.get('raw_state') == ShopStates.waiting_search_query.state:
                return 'search'

            text = event.text or ""
            if text.startswith('/start'):
                return 'shop_view'
            elif text.startswith('/'):
                return 'command'

        return 'default'

    async def _check_admin_bypass(self, user_id: int) -> bool:
        """Checks if the user is an admin (delegates to AuthenticationMiddleware cache)"""
        if not self.config.admin_bypass:
            return False

        try:
            if self.auth_middleware:
                role = await self.auth_middleware.get_user_role_cached(user_id)
            else:
                from bot.database.methods import check_role
                role = await check_role(user_id) or 0
            return Permission.has_any_admin_perm(role)
        except Exception:
            return False

    def _backend(self):
        """Return the Redis-backed limiter when Redis is healthy, else None.

        Falls back to the in-memory limiter (per-process) whenever caching is
        disabled or Redis is down, preserving the single-instance behaviour.
        """
        from bot.misc.caching import get_cache_manager
        cache = get_cache_manager()
        if cache is not None and getattr(cache, "_healthy", False) and getattr(cache, "redis", None) is not None:
            if self._redis_limiter is None or self._redis_limiter.redis is not cache.redis:
                self._redis_limiter = RedisRateLimiter(self.config, cache.redis, self.limiter)
            return self._redis_limiter
        return None

    async def _is_banned(self, user_id: int) -> bool:
        backend = self._backend()
        return await backend.is_banned(user_id) if backend else self.limiter.is_banned(user_id)

    async def _ban_user(self, user_id: int) -> None:
        backend = self._backend()
        if backend:
            await backend.ban_user(user_id)
        else:
            self.limiter.ban_user(user_id)

    async def _check_global_limit(self, user_id: int) -> bool:
        backend = self._backend()
        return await backend.check_global_limit(user_id) if backend else self.limiter.check_global_limit(user_id)

    async def _check_action_limit(self, user_id: int, action: str) -> bool:
        backend = self._backend()
        return await backend.check_action_limit(user_id, action) if backend else self.limiter.check_action_limit(
            user_id, action)

    async def _get_wait_time(self, user_id: int, action: str = None) -> int:
        backend = self._backend()
        return await backend.get_wait_time(user_id, action) if backend else self.limiter.get_wait_time(user_id, action)

    async def __call__(
            self,
            handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
            event: TelegramObject,
            data: Dict[str, Any]
    ) -> Any:
        """Basic middleware logic"""

        # Define the user
        user = None
        if isinstance(event, Message):
            user = event.from_user
        elif isinstance(event, CallbackQuery):
            user = event.from_user

        if not user:
            return await handler(event, data)

        user_id = user.id

        # Resolved up front so the limiter call can honour it server-side: an admin is still ban-checked but skips both windows.
        # The role comes from the in-process cache on all but the first lookup.
        bypass = await self._check_admin_bypass(user_id)

        # Define action
        action = self._get_action_from_event(event, data)

        # Ban check plus both sliding windows, resolved in a single call.
        backend = self._backend()
        if backend is not None:
            verdict, wait_time = await backend.check(user_id, action, bypass)
        else:
            verdict, wait_time = self.limiter.check(user_id, action, bypass)

        if verdict == ALLOWED:
            return await handler(event, data)

        if verdict == BANNED:
            message = localize("middleware.ban", time=wait_time)
        elif verdict == GLOBAL_EXCEEDED:
            message = localize("middleware.above_limits")
        else:
            message = localize("middleware.waiting", time=wait_time)

        if isinstance(event, CallbackQuery):
            await event.answer(message, show_alert=True)
        elif isinstance(event, Message):
            try:
                await event.answer(message)
            except TelegramBadRequest as e:
                logger.debug(f"Rate limit notification failed: {e}")
        return None


# Function for quick setup
def setup_rate_limiting(dp, config: RateLimitConfig = None, auth_middleware=None):
    """Connects rate limiting to the dispatcher"""
    middleware = RateLimitMiddleware(config, auth_middleware=auth_middleware)
    dp.message.middleware(middleware)
    dp.callback_query.middleware(middleware)
    return middleware
