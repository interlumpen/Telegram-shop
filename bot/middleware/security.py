import time
from typing import Dict, Any, Callable, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, CallbackQuery, Message

from bot.i18n import localize
from bot.database.methods.audit import log_audit


def check_suspicious_patterns(text: str) -> bool:
    """Checking for suspicious patterns in callback data"""
    if not text:
        return False

    # Length check (DoS protection)
    if len(text) > 4096:
        return True

    import re
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
            'buy_', 'pay_', 'delete_', 'admin', 'remove-admin',
            'fill-user-balance', 'set-admin', 'deduct-user-balance'
        }

    def is_critical_action(self, callback_data: str) -> bool:
        """Checking whether an action is critical"""
        if not callback_data:
            return False

        return any(
            callback_data.startswith(action)
            for action in self.critical_actions
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
                # Logging a critical action
                log_audit(
                    "critical_action",
                    user_id=user.id,
                    details=f"callback={event.data[:50]}",
                )

                # Check that the callback is not too old (protection against replay attacks)
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
                log_audit(
                    "suspicious_callback",
                    level="WARNING",
                    user_id=user.id,
                    details=f"data={event.data[:100]}",
                )
                await event.answer(localize("middleware.security.invalid_data"), show_alert=True)
                return None

        if isinstance(event, Message) and event.text:
            if check_suspicious_patterns(event.text):
                log_audit(
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
        self.admin_cache: Dict[int, tuple[int, float]] = {}  # user_id: (role, timestamp)
        self.cache_ttl = 300  # 5 minutes
        self.maintenance_mode: bool = False

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

        # Checking blocked users (from DB and memory cache)
        from bot.database.methods import is_user_blocked
        if user.id in self.blocked_users or await is_user_blocked(user.id):
            self.blocked_users.add(user.id)  # Update memory cache
            if isinstance(event, CallbackQuery):
                await event.answer(localize("middleware.security.blocked"), show_alert=True)
            return None

        # Check bot
        if user.is_bot:
            log_audit("bot_interaction", level="WARNING", user_id=user.id)
            return None

        # Maintenance mode: block regular users
        if self.maintenance_mode:
            role = await self.get_user_role_cached(user.id)
            if role <= 1:
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
                if role <= 1:  # Not admin
                    await event.answer(localize("middleware.security.not_admin"), show_alert=True)
                    log_audit("unauthorized_admin_access", level="WARNING", user_id=user.id)
                    return None
                data['user_role'] = role

        return await handler(event, data)

    async def get_user_role_cached(self, user_id: int) -> int:
        """Getting a user role with caching"""
        # Check cache
        if user_id in self.admin_cache:
            role, timestamp = self.admin_cache[user_id]
            if time.time() - timestamp < self.cache_ttl:
                return role

        # Download from DB
        from bot.database.methods import check_role
        role = await check_role(user_id) or 0

        # Refresh cache
        self.admin_cache[user_id] = (role, time.time())

        return role

    async def block_user(self, user_id: int) -> bool:
        """Block a user (saves to DB and memory cache)"""
        from bot.database.methods import set_user_blocked
        success = await set_user_blocked(user_id, True)
        if success:
            self.blocked_users.add(user_id)
            log_audit("block_user", user_id=user_id, resource_type="User", resource_id=str(user_id))
        return success

    async def unblock_user(self, user_id: int) -> bool:
        """Unblock a user (saves to DB and removes from memory cache)"""
        from bot.database.methods import set_user_blocked
        success = await set_user_blocked(user_id, False)
        if success:
            self.blocked_users.discard(user_id)
            log_audit("unblock_user", user_id=user_id, resource_type="User", resource_id=str(user_id))
        return success
