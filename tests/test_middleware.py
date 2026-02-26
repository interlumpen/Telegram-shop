import time

from bot.middleware.security import check_suspicious_patterns, SecurityMiddleware, AuthenticationMiddleware
from bot.middleware.rate_limit import RateLimiter, RateLimitConfig


class TestSuspiciousPatterns:

    def test_safe_input(self):
        assert check_suspicious_patterns("Hello, world!") is False

    def test_empty_string(self):
        assert check_suspicious_patterns("") is False

    def test_none(self):
        assert check_suspicious_patterns(None) is False

    def test_sql_injection_union_select(self):
        assert check_suspicious_patterns("1 UNION SELECT * FROM users") is True

    def test_sql_injection_delete(self):
        assert check_suspicious_patterns("1; DELETE FROM users") is True

    def test_xss_script_tag(self):
        assert check_suspicious_patterns("<script>alert(1)</script>") is True

    def test_xss_javascript_protocol(self):
        assert check_suspicious_patterns("javascript:alert(1)") is True

    def test_command_injection_pipe(self):
        assert check_suspicious_patterns("test | cat /etc/passwd") is True

    def test_command_injection_backtick(self):
        assert check_suspicious_patterns("test `whoami`") is True

    def test_path_traversal(self):
        assert check_suspicious_patterns("../../etc/passwd") is True

    def test_long_string(self):
        assert check_suspicious_patterns("x" * 5000) is True

    def test_normal_callback_data(self):
        assert check_suspicious_patterns("shop") is False
        assert check_suspicious_patterns("buy_item_123") is False
        assert check_suspicious_patterns("profile") is False


class TestSecurityMiddlewareCSRF:

    def setup_method(self):
        self.middleware = SecurityMiddleware(secret_key="test_secret_key")

    def test_generate_and_verify_token(self):
        token = self.middleware.generate_token(12345, "buy_widget")
        assert self.middleware.verify_token(token, 12345, "buy_widget") is True

    def test_token_wrong_user(self):
        token = self.middleware.generate_token(12345, "buy_widget")
        assert self.middleware.verify_token(token, 99999, "buy_widget") is False

    def test_token_wrong_action(self):
        token = self.middleware.generate_token(12345, "buy_widget")
        assert self.middleware.verify_token(token, 12345, "buy_other") is False

    def test_token_expired(self):
        token = self.middleware.generate_token(12345, "buy_widget")
        # Verify with max_age=-1 so it's immediately expired (> check, not >=)
        assert self.middleware.verify_token(token, 12345, "buy_widget", max_age=-1) is False

    def test_invalid_token_format(self):
        assert self.middleware.verify_token("invalid", 12345, "buy") is False

    def test_tampered_signature(self):
        token = self.middleware.generate_token(12345, "buy_widget")
        tampered = token[:-5] + "xxxxx"
        assert self.middleware.verify_token(tampered, 12345, "buy_widget") is False


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

    def test_empty_string(self):
        assert self.middleware.is_critical_action("") is False

    def test_none(self):
        assert self.middleware.is_critical_action(None) is False


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

    def test_block_user(self, user_factory):
        user_factory(telegram_id=200001)
        result = self.auth.block_user(200001)
        assert result is True
        assert 200001 in self.auth.blocked_users

    def test_unblock_user(self, user_factory):
        user_factory(telegram_id=200002)
        self.auth.block_user(200002)
        result = self.auth.unblock_user(200002)
        assert result is True
        assert 200002 not in self.auth.blocked_users

    def test_block_nonexistent_user(self):
        result = self.auth.block_user(999999999)
        assert result is False
