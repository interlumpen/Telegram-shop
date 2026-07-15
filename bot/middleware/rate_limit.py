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
        'payment': (10, 60),    # 10 times a minute
        'shop_view': (60, 60),  # 60 times per minute — browsing and paging
        'buy_item': (5, 60),    # 5 purchases a minute
        'search': (10, 60),     # 10 new searches a minute — each is a LIKE scan
        'top_up': (5, 300),     # 5 top-ups in 5 minutes
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


class RedisRateLimiter:
    """Distributed rate limiter backed by Redis (shared across processes).

    Uses one sorted set per (scope, user) as a sliding window of request
    timestamps, and a TTL key for temporary bans. On any Redis error every
    method transparently delegates to the in-memory fallback limiter, so the
    bot never fails closed when Redis is unavailable.
    """

    def __init__(self, config: RateLimitConfig, redis, fallback: "RateLimiter"):
        self.config = config
        self.redis = redis
        self.fallback = fallback

    @staticmethod
    def _member() -> str:
        # Unique per request so identical-timestamp entries don't collapse.
        return f"{time.time():.6f}:{uuid4().hex}"

    async def _allow(self, key: str, window: int, limit: int) -> bool:
        now = time.time()
        await self.redis.zremrangebyscore(key, 0, now - window)
        count = await self.redis.zcard(key)
        if count >= limit:
            return False
        await self.redis.zadd(key, {self._member(): now})
        await self.redis.pexpire(key, int(window * 1000))
        return True

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
                return 'admin_action'

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
        return await backend.check_action_limit(user_id, action) if backend else self.limiter.check_action_limit(user_id, action)

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

        # Checking the ban
        if await self._is_banned(user_id):
            wait_time = await self._get_wait_time(user_id)

            if isinstance(event, CallbackQuery):
                await event.answer(
                    localize("middleware.ban", time=wait_time),
                    show_alert=True
                )
                return None
            elif isinstance(event, Message):
                await event.answer(
                    localize("middleware.ban", time=wait_time)
                )
                return None

        # Check bypass for admins
        if await self._check_admin_bypass(user_id):
            return await handler(event, data)

        # Define action
        action = self._get_action_from_event(event, data)

        # Checking the limits
        if not await self._check_global_limit(user_id):
            await self._ban_user(user_id)

            if isinstance(event, CallbackQuery):
                await event.answer(
                    localize("middleware.above_limits"),
                    show_alert=True
                )
            elif isinstance(event, Message):
                await event.answer(localize("middleware.above_limits"))
            return None

        if not await self._check_action_limit(user_id, action):
            wait_time = await self._get_wait_time(user_id, action)

            if isinstance(event, CallbackQuery):
                await event.answer(
                    localize("middleware.waiting", time=wait_time),
                    show_alert=True
                )
            elif isinstance(event, Message):
                try:
                    await event.answer(localize("middleware.waiting", time=wait_time))
                except TelegramBadRequest as e:
                    logger.debug(f"Rate limit notification failed: {e}")
            return None

        # skip ahead
        return await handler(event, data)


# Function for quick setup
def setup_rate_limiting(dp, config: RateLimitConfig = None, auth_middleware=None):
    """Connects rate limiting to the dispatcher"""
    middleware = RateLimitMiddleware(config, auth_middleware=auth_middleware)
    dp.message.middleware(middleware)
    dp.callback_query.middleware(middleware)
    return middleware
