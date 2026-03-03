import time

from bot.web.admin import LoginRateLimiter


class TestLoginRateLimiter:

    def test_not_blocked_initially(self):
        limiter = LoginRateLimiter(max_attempts=3, lockout_seconds=60)
        assert limiter.is_blocked("1.2.3.4") is False

    def test_blocked_after_max_attempts(self):
        limiter = LoginRateLimiter(max_attempts=3, lockout_seconds=60)

        for _ in range(3):
            limiter.record_failure("1.2.3.4")

        assert limiter.is_blocked("1.2.3.4") is True

    def test_not_blocked_under_max_attempts(self):
        limiter = LoginRateLimiter(max_attempts=3, lockout_seconds=60)

        limiter.record_failure("1.2.3.4")
        limiter.record_failure("1.2.3.4")

        assert limiter.is_blocked("1.2.3.4") is False

    def test_different_ips_independent(self):
        limiter = LoginRateLimiter(max_attempts=2, lockout_seconds=60)

        limiter.record_failure("1.1.1.1")
        limiter.record_failure("1.1.1.1")

        assert limiter.is_blocked("1.1.1.1") is True
        assert limiter.is_blocked("2.2.2.2") is False

    def test_reset_clears_failures(self):
        limiter = LoginRateLimiter(max_attempts=2, lockout_seconds=60)

        limiter.record_failure("1.2.3.4")
        limiter.record_failure("1.2.3.4")
        assert limiter.is_blocked("1.2.3.4") is True

        limiter.reset("1.2.3.4")
        assert limiter.is_blocked("1.2.3.4") is False

    def test_lockout_expires(self):
        limiter = LoginRateLimiter(max_attempts=2, lockout_seconds=1)

        limiter.record_failure("1.2.3.4")
        limiter.record_failure("1.2.3.4")
        assert limiter.is_blocked("1.2.3.4") is True

        time.sleep(1.1)
        assert limiter.is_blocked("1.2.3.4") is False
