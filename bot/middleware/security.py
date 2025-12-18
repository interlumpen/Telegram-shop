import hmac
import hashlib
import time
import secrets
from typing import Dict, Any, Callable, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, CallbackQuery, Message

from bot.i18n import localize
from bot.logger_mesh import audit_logger


def check_suspicious_patterns(text: str) -> bool:
    """Checking for suspicious patterns"""
    if not text:
        return False

    suspicious = [
        # SQL injection
        r"(union.*select|select.*from|insert.*into|delete.*from)",
        # Script injection
        r"<script|javascript:|onerror=|onclick=",
        # Command injection
        r"(;|\||&&|`|\$\()",
        # Path traversal
        r"\.\.\/|\.\.\\",
        # Excessively long strings (possible DoS attack)
    ]

    # Length check
    if len(text) > 4096:
        return True

    import re
    for pattern in suspicious:
        if re.search(pattern, text, re.IGNORECASE):
            return True

    return False


class SecurityMiddleware(BaseMiddleware):
    """
    Middleware for additional security:
    - CSRF protection for critical operations
    - Callback data signature verification
    - Suspicious activity logging
    """

    def __init__(self, secret_key: str = None):
        self.secret_key = secret_key or secrets.token_urlsafe(32)
        self.critical_actions = {
            'buy_', 'pay_', 'delete_', 'admin', 'remove-admin',
            'fill-user-balance', 'set-admin'
        }

    def generate_token(self, user_id: int, action: str) -> str:
        """CSRF token generation"""
        timestamp = str(int(time.time()))
        data = f"{user_id}:{action}:{timestamp}"

        signature = hmac.new(
            self.secret_key.encode(),
            data.encode(),
            hashlib.sha256
        ).hexdigest()

        return f"{data}:{signature}"

    def verify_token(self, token: str, user_id: int, action: str, max_age: int = 3600) -> bool:
        """CSRF token validation"""
        try:
            parts = token.split(':')
            if len(parts) != 4:
                return False

            token_user_id, token_action, timestamp, signature = parts

            # Check user_id and action
            if str(user_id) != token_user_id or action != token_action:
                return False

            # Checking token lifetime
            if int(time.time()) - int(timestamp) > max_age:
                return False

            # Signature verification
            data = f"{token_user_id}:{token_action}:{timestamp}"
            expected_signature = hmac.new(
                self.secret_key.encode(),
                data.encode(),
                hashlib.sha256
            ).hexdigest()

            return hmac.compare_digest(signature, expected_signature)

        except Exception:
            return False

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
                audit_logger.info(
                    f"Critical action: user={user.id}, action={event.data[:50]}"
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
                audit_logger.warning(
                    f"Suspicious callback data from user {user.id}: {event.data[:100]}"
                )
                await event.answer(localize("middleware.security.invalid_data"), show_alert=True)
                return None

        if isinstance(event, Message) and event.text:
            if check_suspicious_patterns(event.text):
                audit_logger.warning(
                    f"Suspicious message from user {user.id}: {event.text[:100]}"
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
        if user.id in self.blocked_users or is_user_blocked(user.id):
            self.blocked_users.add(user.id)  # Update memory cache
            if isinstance(event, CallbackQuery):
                await event.answer(localize("middleware.security.blocked"), show_alert=True)
            return None

        # Check bot
        if user.is_bot:
            audit_logger.warning(f"Bot attempted to interact: {user.id}")
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
                    audit_logger.warning(f"Unauthorized admin access attempt by user {user.id}")
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
        role = check_role(user_id) or 0

        # Refresh cache
        self.admin_cache[user_id] = (role, time.time())

        return role

    def block_user(self, user_id: int) -> bool:
        """Block a user (saves to DB and memory cache)"""
        from bot.database.methods import set_user_blocked
        success = set_user_blocked(user_id, True)
        if success:
            self.blocked_users.add(user_id)
            audit_logger.info(f"User {user_id} has been blocked")
        return success

    def unblock_user(self, user_id: int) -> bool:
        """Unblock a user (saves to DB and removes from memory cache)"""
        from bot.database.methods import set_user_blocked
        success = set_user_blocked(user_id, False)
        if success:
            self.blocked_users.discard(user_id)
            audit_logger.info(f"User {user_id} has been unblocked")
        return success
