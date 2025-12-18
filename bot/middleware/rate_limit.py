import time
from typing import Dict, Any, Callable, Awaitable
from collections import defaultdict
from dataclasses import dataclass, field

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, TelegramObject
from aiogram.exceptions import TelegramBadRequest

from bot.i18n import localize


@dataclass
class RateLimitConfig:
    """Configuration for rate limiting"""
    # Global limits
    global_limit: int = 30  # requests
    global_window: int = 60  # seconds

    # Limits for specific actions
    action_limits: dict = field(default_factory=lambda: {
        'payment': (10, 60),  # 10 times a minute
        'shop_view': (60, 60),  # 60 times per minute
        'buy_item': (5, 60),  # 5 buys a minute
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

        # Checking the limit
        if len(self.user_requests[user_id]) >= self.config.global_limit:
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

        # Checking the limit
        if len(self.user_actions[action][user_id]) >= limit:
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
            requests = self.user_actions[action][user_id]
            if len(requests) >= limit:
                oldest_request = min(requests)
                return int(window - (time.time() - oldest_request))

        # Global limit
        if len(self.user_requests[user_id]) >= self.config.global_limit:
            oldest_request = min(self.user_requests[user_id])
            return int(self.config.global_window - (time.time() - oldest_request))

        return 0


class RateLimitMiddleware(BaseMiddleware):
    """Middleware to limit the frequency of requests"""

    def __init__(self, config: RateLimitConfig = None):
        self.config = config or RateLimitConfig()
        self.limiter = RateLimiter(self.config)
        self.action_mapping = {
            # Callback data -> action name
            'replenish_balance': 'top_up',
            'pay_': 'payment',
            'buy_': 'buy_item',
            'shop': 'shop_view',
            'category_': 'shop_view',
            'item_': 'shop_view',
        }
        # Cache for admin role checks
        self.admin_cache: dict[int, tuple[int, float]] = {}
        self.cache_ttl = 300  # 5 minutes

    def _get_action_from_event(self, event: TelegramObject) -> str:
        """Determines the action from the event"""
        if isinstance(event, CallbackQuery):
            data = event.data or ""
            for prefix, action in self.action_mapping.items():
                if data.startswith(prefix):
                    return action

        elif isinstance(event, Message):
            text = event.text or ""
            if text.startswith('/start'):
                return 'shop_view'
            elif text.startswith('/'):
                return 'admin_action'

        return 'default'

    async def _check_admin_bypass(self, user_id: int) -> bool:
        """Checks if the user is an admin (with caching)"""
        if not self.config.admin_bypass:
            return False

        # Check cache first
        if user_id in self.admin_cache:
            role, timestamp = self.admin_cache[user_id]
            if time.time() - timestamp < self.cache_ttl:
                return role > 1

        try:
            from bot.database.methods import check_role
            role = check_role(user_id) or 0
            # Update cache
            self.admin_cache[user_id] = (role, time.time())
            return role > 1  # ADMIN or OWNER
        except Exception:
            return False

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
        if self.limiter.is_banned(user_id):
            wait_time = self.limiter.get_wait_time(user_id)

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
        action = self._get_action_from_event(event)

        # Checking the limits
        if not self.limiter.check_global_limit(user_id):
            self.limiter.ban_user(user_id)

            if isinstance(event, CallbackQuery):
                await event.answer(
                    localize("middleware.above_limits"),
                    show_alert=True
                )
            elif isinstance(event, Message):
                await event.answer(localize("middleware.above_limits"))
            return None

        if not self.limiter.check_action_limit(user_id, action):
            wait_time = self.limiter.get_wait_time(user_id, action)

            if isinstance(event, CallbackQuery):
                await event.answer(
                    localize("middleware.waiting", time=wait_time),
                    show_alert=True
                )
            elif isinstance(event, Message):
                try:
                    await event.answer(localize("middleware.waiting", time=wait_time))
                except TelegramBadRequest as e:
                    # Ignore message sending errors (deleted chat, etc.)
                    pass
            return None

        # skip ahead
        return await handler(event, data)


# Function for quick setup
def setup_rate_limiting(dp, config: RateLimitConfig = None):
    """Connects rate limiting to the dispatcher"""
    middleware = RateLimitMiddleware(config)
    dp.message.middleware(middleware)
    dp.callback_query.middleware(middleware)
    return middleware
