import time

import pytest

from bot.middleware.security import check_suspicious_patterns, SecurityMiddleware, AuthenticationMiddleware
from bot.middleware.rate_limit import RateLimiter, RateLimitConfig


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
