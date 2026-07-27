import pytest
from unittest.mock import patch, MagicMock
from aiogram.enums import ChatMemberStatus

from bot.handlers.other import (
    check_sub_channel, _any_payment_method_enabled, generate_short_hash, is_safe_item_name,
    caller_name, display_name,
)


class TestCallerName:
    """Audit entries name the caller from the update itself; only a *different*
    user's name is worth a get_chat round-trip."""

    def test_uses_the_first_name_on_the_update(self, make_callback_query):
        call = make_callback_query(data="x", user_id=555)
        call.from_user.first_name = "Ann"

        assert caller_name(call) == "Ann"

    def test_falls_back_to_the_id_when_unnamed(self, make_message):
        msg = make_message(text="x", user_id=556)
        msg.from_user.first_name = None

        assert caller_name(msg) == "556"

    def test_survives_an_update_without_a_sender(self):
        assert caller_name(MagicMock(from_user=None)) == "unknown"

    def test_makes_no_api_call(self, make_callback_query):
        call = make_callback_query(data="x", user_id=557)
        call.from_user.first_name = "Bob"

        caller_name(call)

        call.message.bot.get_chat.assert_not_called()


class TestDisplayName:

    async def test_reads_another_users_name_over_the_api(self, mock_bot):
        mock_bot.get_chat.return_value = MagicMock(first_name="Other")

        assert await display_name(mock_bot, 999) == "Other"
        mock_bot.get_chat.assert_awaited_once_with(999)

    async def test_falls_back_to_the_id_when_the_api_refuses(self, mock_bot):
        from aiogram.exceptions import TelegramForbiddenError

        mock_bot.get_chat.side_effect = TelegramForbiddenError(
            method=MagicMock(), message="blocked"
        )

        assert await display_name(mock_bot, 999) == "999"


class TestCheckSubChannel:

    @pytest.mark.parametrize("status,expected", [
        (ChatMemberStatus.MEMBER, True),
        (ChatMemberStatus.ADMINISTRATOR, True),
        (ChatMemberStatus.CREATOR, True),
        (ChatMemberStatus.LEFT, False),
        (ChatMemberStatus.KICKED, False),
    ])
    async def test_subscription_status(self, status, expected):
        member = MagicMock()
        member.status = status
        assert await check_sub_channel(member) is expected


class TestAnyPaymentMethodEnabled:

    @pytest.mark.parametrize("crypto,stars,provider,expected", [
        ("token", 0.91, "provider", True),  # all three configured
        ("", 0, "", False),                 # none configured
        ("token", 0, "", True),             # crypto only
        ("", 0.91, "", True),               # stars only
    ])
    def test_enabled(self, crypto, stars, provider, expected):
        with patch('bot.handlers.other.EnvKeys') as env:
            env.CRYPTO_PAY_TOKEN = crypto
            env.STARS_PER_VALUE = stars
            env.TELEGRAM_PROVIDER_TOKEN = provider
            assert _any_payment_method_enabled() is expected


class TestGenerateShortHash:

    def test_deterministic(self):
        assert generate_short_hash("test") == generate_short_hash("test")

    @pytest.mark.parametrize("kwargs,expected_length", [
        ({}, 8),
        ({"length": 12}, 12),
    ])
    def test_length(self, kwargs, expected_length):
        assert len(generate_short_hash("test", **kwargs)) == expected_length

    def test_different_inputs_different_hashes(self):
        assert generate_short_hash("hello") != generate_short_hash("world")


class TestIsSafeItemName:

    @pytest.mark.parametrize("name,expected", [
        ("Normal Product", True),
        ("Товар 🎮", True),      # unicode and emoji are fine
        ("A", True),
        ("A" * 100, True),       # exactly at the cap
        ("A" * 101, False),      # one over the cap
        ("", False),
        ("item\x00name", False),  # control characters
        ("item\x1fname", False),
        ("item\x7fname", False),
    ])
    def test_name_acceptance(self, name, expected):
        assert is_safe_item_name(name) is expected


class TestLoggingConfig:
    def test_file_logging_goes_through_queue_handlers(self, tmp_path, monkeypatch):
        """File handlers must sit behind a QueueListener so disk writes never
        block the event loop; shutdown flushes the queue."""
        from logging.handlers import QueueHandler
        import bot.logger_mesh as lm

        monkeypatch.setattr('bot.misc.env.EnvKeys.LOG_TO_FILE', '1')
        monkeypatch.setattr('bot.misc.env.EnvKeys.BOT_LOGFILE', str(tmp_path / 'bot.log'))
        monkeypatch.setattr('bot.misc.env.EnvKeys.BOT_AUDITFILE', str(tmp_path / 'audit.log'))

        prev_bot = lm.logger.handlers[:]
        prev_audit = lm.audit_logger.handlers[:]
        try:
            logger, audit_logger = lm.configure_logging(console=False)

            assert any(isinstance(h, QueueHandler) for h in logger.handlers)
            assert any(isinstance(h, QueueHandler) for h in audit_logger.handlers)
            assert len(lm._listeners) == 2

            logger.info("queued line")
            lm.shutdown_logging()

            assert lm._listeners == []
            assert "queued line" in (tmp_path / 'bot.log').read_text(encoding='utf-8')
        finally:
            lm.shutdown_logging()
            lm.logger.handlers[:] = prev_bot
            lm.audit_logger.handlers[:] = prev_audit
