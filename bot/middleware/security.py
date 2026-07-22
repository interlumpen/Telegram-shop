import re
import time
from typing import Dict, Any, Callable, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, CallbackQuery, Message

from bot.i18n import localize
from bot.database.methods.audit import log_audit_bg
from bot.database.models import Permission


def check_suspicious_patterns(text: str) -> bool:
    """Checking for suspicious patterns in callback data"""
    if not text:
        return False

    # Length check (DoS protection)
    if len(text) > 4096:
        return True

    # Check for script injection
    if re.search(r"<script|javascript:|onerror=|onclick=", text, re.IGNORECASE):
        return True

    return False


class SecurityMiddleware(BaseMiddleware):
    """
    Middleware for additional security:
    - Audit logging for critical operations
    - Replay attack prevention
    - Suspicious activity logging
    """

    def __init__(self):
        self.critical_actions = {
            'buy_', 'pay_', 'delete_', 'admin',
            'fill-user-balance', 'deduct-user-balance',
            'role_mgmt', 'role_new', 'role_d', 'asr_'
        }
        # Only transactional actions get replay protection (message age check)
        self.replay_protected_actions = {
            'buy_', 'pay_', 'fill-user-balance', 'deduct-user-balance',
        }

    def is_critical_action(self, callback_data: str) -> bool:
        """Checking whether an action is critical"""
        if not callback_data:
            return False

        return any(
            callback_data.startswith(action)
            for action in self.critical_actions
        )

    def is_replay_protected(self, callback_data: str) -> bool:
        """Check if this action needs replay attack protection"""
        if not callback_data:
            return False

        return any(
            callback_data.startswith(action)
            for action in self.replay_protected_actions
        )

    async def __call__(
            self,
            handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
            event: TelegramObject,
            data: Dict[str, Any]
    ) -> Any:
        """Basic middleware logic"""

        # Get the user
        user = None
        if isinstance(event, Message):
            user = event.from_user
        elif isinstance(event, CallbackQuery):
            user = event.from_user

            # Checking critical actions
            if self.is_critical_action(event.data):
                # Logging a critical action (off the request path)
                log_audit_bg(
                    "critical_action",
                    user_id=user.id,
                    details=f"callback={event.data[:50]}",
                )

            # Replay protection only for transactional actions (buy, pay, balance)
            if self.is_replay_protected(event.data):
                if hasattr(event.message, 'date'):
                    message_age = time.time() - event.message.date.timestamp()
                    if message_age > 3600:  # 1 hour
                        await event.answer(
                            localize("middleware.security.session_outdated"),
                            show_alert=True
                        )
                        return None

        # Check for suspicious patterns in the data
        if isinstance(event, CallbackQuery) and event.data:
            if check_suspicious_patterns(event.data):
                log_audit_bg(
                    "suspicious_callback",
                    level="WARNING",
                    user_id=user.id,
                    details=f"data={event.data[:100]}",
                )
                await event.answer(localize("middleware.security.invalid_data"), show_alert=True)
                return None

        if isinstance(event, Message) and event.text:
            if check_suspicious_patterns(event.text):
                log_audit_bg(
                    "suspicious_message",
                    level="WARNING",
                    user_id=user.id,
                    details=f"text={event.text[:100]}",
                )
                # We don't block messages, we just log them

        # Pass it on
        return await handler(event, data)


class AuthenticationMiddleware(BaseMiddleware):
    """
    Middleware for authentication and authorization verification
    """

    def __init__(self):
        self.blocked_users: set[int] = set()
        # True once blocked_users reflects the DB; until then per-update checks
        # fall back to the database (single-instance deployment assumption:
        # every block/unblock in this process keeps the set current).
        self._blocked_loaded: bool = False
        self.admin_cache: Dict[int, tuple[int, float]] = {}  # user_id: (role, timestamp)
        self.cache_ttl = 300  # 5 minutes
        self._maintenance_mode: bool = False

    @property
    def maintenance_mode(self) -> bool:
        return self._maintenance_mode

    @maintenance_mode.setter
    def maintenance_mode(self, value: bool):
        self._maintenance_mode = value
        from bot.misc.caching import get_cache_manager
        cache = get_cache_manager()
        if cache:
            from bot.database.methods.cache_utils import safe_create_task
            safe_create_task(cache.set("bot:maintenance_mode", value, ttl=86400 * 30))

    async def __call__(
            self,
            handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
            event: TelegramObject,
            data: Dict[str, Any]
    ) -> Any:
        """Authentication Check"""

        user = None
        if isinstance(event, (Message, CallbackQuery)):
            user = event.from_user

        if not user:
            return await handler(event, data)

        if self._blocked_loaded:
            blocked = user.id in self.blocked_users
        else:
            # Startup load failed — retry the bulk load; if the DB is still
            # unreachable for that, fall back to a per-update lookup.
            await self._load_blocked_set()
            if self._blocked_loaded:
                blocked = user.id in self.blocked_users
            else:
                from bot.database.methods import is_user_blocked
                blocked = await is_user_blocked(user.id)
        if blocked:
            if isinstance(event, CallbackQuery):
                await event.answer(localize("middleware.security.blocked"), show_alert=True)
            return None

        # Check bot
        if user.is_bot:
            log_audit_bg("bot_interaction", level="WARNING", user_id=user.id)
            return None

        # Maintenance mode: block regular users
        if self.maintenance_mode:
            role = await self.get_user_role_cached(user.id)
            if not Permission.has_any_admin_perm(role):
                if isinstance(event, Message):
                    await event.answer(localize("maintenance.active"))
                elif isinstance(event, CallbackQuery):
                    await event.answer(localize("maintenance.active"), show_alert=True)
                return None

        # Add user information to the context
        data['user_id'] = user.id
        data['user_name'] = user.first_name

        # Role validation and caching for admin actions
        if isinstance(event, CallbackQuery):
            if event.data and any(event.data.startswith(x) for x in ['admin', 'console', 'send_message']):
                role = await self.get_user_role_cached(user.id)
                if not Permission.has_any_admin_perm(role):
                    await event.answer(localize("middleware.security.not_admin"), show_alert=True)
                    log_audit_bg("unauthorized_admin_access", level="WARNING", user_id=user.id)
                    return None
                data['user_role'] = role

        return await handler(event, data)

    async def get_user_role_cached(self, user_id: int) -> int:
        """Getting a user role with caching.

        Reads through a shared Redis cache first (so every worker sees the same
        role and a web-panel edit invalidates all of them), then a per-process
        in-memory cache, then the DB. Writes populate both caches. When Redis is
        unavailable the in-memory cache alone is used (single-instance mode).
        """
        from bot.misc.caching import get_cache_manager
        cache = get_cache_manager()
        redis_ok = cache is not None and getattr(cache, "_healthy", False)

        # 1. Shared Redis cache
        if redis_ok:
            try:
                cached = await cache.get(f"auth:role:{user_id}")
                if cached is not None:
                    return int(cached)
            except Exception:
                redis_ok = False

        # 2. Per-process in-memory cache
        if user_id in self.admin_cache:
            role, timestamp = self.admin_cache[user_id]
            if time.time() - timestamp < self.cache_ttl:
                return role

        # 3. Download from DB
        from bot.database.methods import check_role
        role = await check_role(user_id) or 0

        # Only cache real users. role == 0 means the user does not exist in the DB
        if role:
            self.admin_cache[user_id] = (role, time.time())
            if redis_ok:
                try:
                    await cache.set(f"auth:role:{user_id}", role, ttl=self.cache_ttl)
                except Exception:
                    pass

        return role

    def invalidate_admin_cache(self, user_id: int) -> None:
        """Remove cached role for a user so permissions are re-fetched."""
        self.admin_cache.pop(user_id, None)
        _drop_redis_role(user_id)

    async def _load_blocked_set(self) -> None:
        """Load the blocked-user set from DB; on success it becomes authoritative."""
        from bot.database.methods.read import get_blocked_user_ids
        try:
            self.blocked_users = set(await get_blocked_user_ids())
            self._blocked_loaded = True
        except Exception:
            pass  # Will fall back to per-request DB checks

    async def load_blocked_users(self) -> None:
        """Load blocked users from DB into memory cache on startup."""
        await self._load_blocked_set()

        # Restore maintenance mode from Redis
        from bot.misc.caching import get_cache_manager
        cache = get_cache_manager()
        if cache:
            try:
                val = await cache.get("bot:maintenance_mode")
                if val is not None:
                    self._maintenance_mode = bool(val)
            except Exception:
                pass

    async def block_user(self, user_id: int) -> bool:
        """Block a user (saves to DB and memory cache)"""
        from bot.database.methods import set_user_blocked
        success = await set_user_blocked(user_id, True)
        if success:
            self.blocked_users.add(user_id)
            log_audit_bg("block_user", user_id=user_id, resource_type="User", resource_id=str(user_id))
        return success

    async def unblock_user(self, user_id: int) -> bool:
        """Unblock a user (saves to DB and removes from memory cache)"""
        from bot.database.methods import set_user_blocked
        success = await set_user_blocked(user_id, False)
        if success:
            self.blocked_users.discard(user_id)
            log_audit_bg("unblock_user", user_id=user_id, resource_type="User", resource_id=str(user_id))
        return success


_auth_middleware_instance: "AuthenticationMiddleware | None" = None


def set_auth_middleware(instance: "AuthenticationMiddleware") -> None:
    """Register the live AuthenticationMiddleware instance (called at startup)."""
    global _auth_middleware_instance
    _auth_middleware_instance = instance


def get_auth_middleware() -> "AuthenticationMiddleware | None":
    """Return the live AuthenticationMiddleware instance registered at startup."""
    return _auth_middleware_instance


def _drop_redis_role(user_id: int) -> None:
    """Schedule deletion of one user's shared role cache entry (best-effort)."""
    from bot.misc.caching import get_cache_manager
    cache = get_cache_manager()
    if cache is not None:
        from bot.database.methods.cache_utils import safe_create_task
        safe_create_task(cache.delete(f"auth:role:{user_id}"))


def invalidate_auth_caches(user_id: int, *, blocked: bool | None = None) -> None:
    """Drop the role cache (Redis + in-memory) for one user and sync the blocked set.

    Needed after a web-panel edit changes a user's role or block state, so no
    worker keeps serving the stale permission/block state until TTL expiry.

    The in-memory blocked set is the per-update source of truth, so callers
    that change block state must pass ``blocked``; ``None`` (role-only change)
    leaves the set untouched.
    """
    inst = _auth_middleware_instance
    if inst is not None:
        inst.admin_cache.pop(user_id, None)
        if blocked is True:
            inst.blocked_users.add(user_id)
        elif blocked is False:
            inst.blocked_users.discard(user_id)
    _drop_redis_role(user_id)


def clear_role_auth_caches() -> None:
    """Flush the entire role cache (Redis + in-memory).

    A Role's permission bitmask affects every user holding that role, so a Role
    edit cannot be scoped to a single user id — clear the whole cache on every
    worker via a Redis pattern delete plus the local map.
    """
    inst = _auth_middleware_instance
    if inst is not None:
        inst.admin_cache.clear()

    from bot.misc.caching import get_cache_manager
    cache = get_cache_manager()
    if cache is not None:
        from bot.database.methods.cache_utils import safe_create_task
        safe_create_task(cache.invalidate_pattern("auth:role:*"))
