import pytest
import time
import warnings
from unittest.mock import MagicMock, AsyncMock, patch
from aiogram.types import Message, CallbackQuery, User as TelegramUser

from bot.middleware import RateLimiter, RateLimitConfig, RateLimitMiddleware
from bot.middleware.security import SecurityMiddleware, AuthenticationMiddleware, check_suspicious_patterns

# Filter Pydantic v2 deprecation warnings from unittest.mock
warnings.filterwarnings("ignore", category=DeprecationWarning,
                       message="The `__fields__` attribute is deprecated, use `model_fields` instead.")
warnings.filterwarnings("ignore", category=DeprecationWarning,
                       module="pydantic._internal._model_construction")

# Add pytest mark to ignore warnings at the module level
pytestmark = [
    pytest.mark.filterwarnings("ignore:The `__fields__` attribute is deprecated:DeprecationWarning"),
    pytest.mark.filterwarnings("ignore::pydantic.warnings.PydanticDeprecatedSince20")
]


class TestRateLimiter:
    """Test suite for rate limiting functionality"""

    def test_rate_limiter_initialization(self):
        """Test rate limiter initialization"""
        config = RateLimitConfig(
            global_limit=10,
            global_window=60,
            ban_duration=300,
            admin_bypass=True
        )
        limiter = RateLimiter(config)

        assert limiter.config.global_limit == 10
        assert limiter.config.global_window == 60
        assert limiter.config.ban_duration == 300
        assert limiter.config.admin_bypass == True

    def test_global_rate_limiting(self):
        """Test global rate limiting"""
        config = RateLimitConfig(
            global_limit=5,
            global_window=10,
            ban_duration=30
        )
        limiter = RateLimiter(config)
        user_id = 12345

        # First 5 requests should pass
        for i in range(5):
            assert limiter.check_global_limit(user_id) == True

        # 6th request should fail
        assert limiter.check_global_limit(user_id) == False

        # User should not be banned yet
        assert limiter.is_banned(user_id) == False

    def test_action_specific_limits(self):
        """Test action-specific rate limits"""
        config = RateLimitConfig(
            global_limit=100,
            global_window=60,
            action_limits={
                'payment': (2, 10),  # 2 payments in 10 seconds
                'broadcast': (1, 3600)  # 1 broadcast per hour
            }
        )
        limiter = RateLimiter(config)
        user_id = 12345

        # Payment limits
        assert limiter.check_action_limit(user_id, 'payment') == True
        assert limiter.check_action_limit(user_id, 'payment') == True
        assert limiter.check_action_limit(user_id, 'payment') == False

        # Broadcast limits
        assert limiter.check_action_limit(user_id, 'broadcast') == True
        assert limiter.check_action_limit(user_id, 'broadcast') == False

        # Unknown action should pass
        assert limiter.check_action_limit(user_id, 'unknown_action') == True

    def test_ban_mechanism(self):
        """Test user banning mechanism"""
        config = RateLimitConfig(
            global_limit=5,
            global_window=10,
            ban_duration=2  # 2 seconds for testing
        )
        limiter = RateLimiter(config)
        user_id = 12345

        # Ban user
        limiter.ban_user(user_id)
        assert limiter.is_banned(user_id) == True

        # Check wait time
        wait_time = limiter.get_wait_time(user_id)
        assert 0 < wait_time <= 2

        # Wait for ban to expire
        time.sleep(2.1)
        assert limiter.is_banned(user_id) == False

    def test_request_cleanup(self):
        """Test old request cleanup"""
        config = RateLimitConfig(
            global_limit=5,
            global_window=2  # 2 seconds window
        )
        limiter = RateLimiter(config)
        user_id = 12345

        # Make 3 requests
        for _ in range(3):
            limiter.check_global_limit(user_id)

        # Wait for window to expire
        time.sleep(2.1)

        # Should be able to make new requests
        for _ in range(5):
            assert limiter.check_global_limit(user_id) == True

    @pytest.mark.asyncio
    async def test_middleware_integration(self):
        """Test RateLimitMiddleware integration"""
        config = RateLimitConfig(
            global_limit=3,
            global_window=10,
            admin_bypass=False
        )
        middleware = RateLimitMiddleware(config)

        # Mock message
        message = MagicMock(spec=Message)
        message.from_user = MagicMock(spec=TelegramUser)
        message.from_user.id = 12345
        message.text = "/start"
        message.answer = AsyncMock()

        # Mock handler
        handler = AsyncMock(return_value="response")

        # First 3 requests should pass
        for _ in range(3):
            result = await middleware(handler, message, {})
            assert result == "response"

        # 4th request should be blocked
        middleware.limiter.ban_user(12345)
        result = await middleware(handler, message, {})
        assert result is None
        message.answer.assert_called()


class TestSecurityMiddleware:
    """Test suite for security middleware"""

    def test_suspicious_patterns_detection(self):
        """Test detection of suspicious patterns"""
        # SQL injection patterns
        assert check_suspicious_patterns("'; DROP TABLE users; --") == True
        assert check_suspicious_patterns("UNION SELECT * FROM passwords") == True

        # Script injection
        assert check_suspicious_patterns("<script>alert('xss')</script>") == True
        assert check_suspicious_patterns("javascript:void(0)") == True
        assert check_suspicious_patterns("onerror=alert(1)") == True

        # Command injection
        assert check_suspicious_patterns("test; rm -rf /") == True
        assert check_suspicious_patterns("test && cat /etc/passwd") == True
        assert check_suspicious_patterns("$(whoami)") == True

        # Path traversal
        assert check_suspicious_patterns("../../etc/passwd") == True
        assert check_suspicious_patterns("..\\windows\\system32") == True

        # Normal text should pass
        assert check_suspicious_patterns("Hello, world!") == False
        assert check_suspicious_patterns("Buy item #123") == False

        # Very long text (DoS attempt)
        assert check_suspicious_patterns("x" * 5000) == True

    def test_csrf_token_generation_and_validation(self):
        """Test CSRF token generation and validation"""
        middleware = SecurityMiddleware(secret_key="test_secret")
        user_id = 12345
        action = "buy_item"

        # Generate token
        token = middleware.generate_token(user_id, action)
        assert token is not None
        assert ":" in token

        # Valid token should pass
        assert middleware.verify_token(token, user_id, action) == True

        # Wrong user_id should fail
        assert middleware.verify_token(token, 99999, action) == False

        # Wrong action should fail
        assert middleware.verify_token(token, user_id, "wrong_action") == False

        # Expired token should fail
        old_token = middleware.generate_token(user_id, action)
        # Manipulate timestamp
        parts = old_token.split(":")
        old_timestamp = str(int(time.time()) - 7200)  # 2 hours ago
        expired_token = f"{parts[0]}:{parts[1]}:{old_timestamp}:{parts[3]}"
        assert middleware.verify_token(expired_token, user_id, action) == False

        # Invalid format should fail
        assert middleware.verify_token("invalid_token", user_id, action) == False

    def test_critical_action_detection(self):
        """Test detection of critical actions"""
        middleware = SecurityMiddleware()

        # Critical actions
        assert middleware.is_critical_action("buy_item_123") == True
        assert middleware.is_critical_action("pay_cryptopay") == True
        assert middleware.is_critical_action("delete_user") == True
        assert middleware.is_critical_action("admin_panel") == True
        assert middleware.is_critical_action("set-admin_123") == True
        assert middleware.is_critical_action("remove-admin_456") == True
        assert middleware.is_critical_action("fill-user-balance_789") == True
        assert middleware.is_critical_action("deduct-user-balance_789") == True

        # Non-critical actions
        assert middleware.is_critical_action("view_profile") == False
        assert middleware.is_critical_action("shop") == False
        assert middleware.is_critical_action("help") == False
        assert middleware.is_critical_action("") == False
        assert middleware.is_critical_action(None) == False

    @pytest.mark.asyncio
    async def test_security_middleware_callback_validation(self):
        """Test security middleware callback validation"""
        middleware = SecurityMiddleware()

        # Mock callback query with suspicious data
        callback = MagicMock(spec=CallbackQuery)
        callback.from_user = MagicMock(spec=TelegramUser)
        callback.from_user.id = 12345
        callback.data = "'; DROP TABLE users; --"
        callback.answer = AsyncMock()
        callback.message = MagicMock()
        callback.message.date = MagicMock()
        callback.message.date.timestamp = MagicMock(return_value=time.time())

        handler = AsyncMock(return_value="response")

        # Should block suspicious callback
        result = await middleware(handler, callback, {})
        assert result is None
        callback.answer.assert_called()

        # Normal callback should pass
        callback.data = "shop_category_1"
        result = await middleware(handler, callback, {})
        assert result == "response"

    @pytest.mark.asyncio
    async def test_security_middleware_old_callback_protection(self):
        """Test protection against old callback replay attacks"""
        middleware = SecurityMiddleware()

        # Mock old callback query
        callback = MagicMock(spec=CallbackQuery)
        callback.from_user = MagicMock(spec=TelegramUser)
        callback.from_user.id = 12345
        callback.data = "buy_item_expensive"
        callback.answer = AsyncMock()
        callback.message = MagicMock()
        callback.message.date = MagicMock()
        # Set message date to 2 hours ago
        callback.message.date.timestamp = MagicMock(return_value=time.time() - 7200)

        handler = AsyncMock(return_value="response")

        # Should block old critical action
        result = await middleware(handler, callback, {})
        assert result is None
        callback.answer.assert_called()


class TestAuthenticationMiddleware:
    """Test suite for authentication middleware"""

    def test_authentication_initialization(self):
        """Test authentication middleware initialization"""
        auth = AuthenticationMiddleware()
        assert auth.blocked_users == set()
        assert auth.admin_cache == {}
        assert auth.cache_ttl == 300

    @patch('bot.database.methods.set_user_blocked', return_value=True)
    def test_user_blocking(self, mock_set_blocked):
        """Test user blocking functionality"""
        auth = AuthenticationMiddleware()
        user_id = 12345

        # Block user
        auth.block_user(user_id)
        assert user_id in auth.blocked_users

        # Unblock user
        auth.unblock_user(user_id)
        assert user_id not in auth.blocked_users

    @pytest.mark.asyncio
    async def test_bot_detection(self):
        """Test bot user detection"""
        auth = AuthenticationMiddleware()

        # Mock message from bot
        message = MagicMock(spec=Message)
        message.from_user = MagicMock(spec=TelegramUser)
        message.from_user.id = 12345
        message.from_user.is_bot = True

        handler = AsyncMock(return_value="response")

        # Should block bot users
        result = await auth(handler, message, {})
        assert result is None

    @pytest.mark.asyncio
    @patch('bot.database.methods.set_user_blocked', return_value=True)
    async def test_blocked_user_handling(self, mock_set_blocked):
        """Test blocked user handling"""
        auth = AuthenticationMiddleware()
        auth.block_user(12345)

        # Mock callback from blocked user
        callback = MagicMock(spec=CallbackQuery)
        callback.from_user = MagicMock(spec=TelegramUser)
        callback.from_user.id = 12345
        callback.from_user.is_bot = False
        callback.from_user.first_name = "TestUser"
        callback.answer = AsyncMock()
        callback.data = "some_action"

        handler = AsyncMock(return_value="response")

        # Should block blocked users
        result = await auth(handler, callback, {})
        assert result is None
        callback.answer.assert_called()

    @pytest.mark.asyncio
    async def test_admin_role_caching(self):
        """Test admin role caching mechanism"""
        auth = AuthenticationMiddleware()
        user_id = 12345

        # Mock check_role function
        with patch('bot.database.methods.check_role') as mock_check_role:
            mock_check_role.return_value = 2  # Admin role

            # First call should query database
            role1 = await auth.get_user_role_cached(user_id)
            assert role1 == 2
            mock_check_role.assert_called_once_with(user_id)

            # Second call should use cache
            mock_check_role.reset_mock()
            role2 = await auth.get_user_role_cached(user_id)
            assert role2 == 2
            mock_check_role.assert_not_called()

            # Clear cache by setting old timestamp
            auth.admin_cache[user_id] = (2, time.time() - 400)  # Expired

            # Should query database again
            mock_check_role.reset_mock()
            role3 = await auth.get_user_role_cached(user_id)
            assert role3 == 2
            mock_check_role.assert_called_once()

    @pytest.mark.asyncio
    async def test_admin_access_control(self):
        """Test admin access control"""
        auth = AuthenticationMiddleware()

        # Mock callback for admin action
        callback = MagicMock(spec=CallbackQuery)
        callback.from_user = MagicMock(spec=TelegramUser)
        callback.from_user.id = 12345
        callback.from_user.is_bot = False
        callback.from_user.first_name = "Test User"
        callback.data = "admin_panel"
        callback.answer = AsyncMock()

        handler = AsyncMock(return_value="response")

        # Non-admin should be blocked
        with patch('bot.database.methods.check_role') as mock_check_role:
            mock_check_role.return_value = 1  # User role

            result = await auth(handler, callback, {})
            assert result is None
            callback.answer.assert_called()

        # Clear the cache before testing admin access
        auth.admin_cache.clear()  # Clear the cache!

        # Admin should pass
        with patch('bot.database.methods.check_role') as mock_check_role:
            mock_check_role.return_value = 2  # Admin role

            # Reset the answer mock
            callback.answer.reset_mock()

            result = await auth(handler, callback, {})
            assert result == "response"

    @pytest.mark.asyncio
    async def test_user_context_injection(self):
        """Test user context injection into data"""
        auth = AuthenticationMiddleware()

        # Mock message
        message = MagicMock(spec=Message)
        message.from_user = MagicMock(spec=TelegramUser)
        message.from_user.id = 12345
        message.from_user.is_bot = False
        message.from_user.first_name = "John"

        handler = AsyncMock(return_value="response")
        data = {}

        # Should inject user data
        result = await auth(handler, message, data)
        assert result == "response"
        assert data['user_id'] == 12345
        assert data['user_name'] == "John"
