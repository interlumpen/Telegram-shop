import pytest
from unittest.mock import patch, MagicMock
from aiogram.enums import ChatMemberStatus


class TestCheckSubChannel:

    @pytest.mark.asyncio
    async def test_member_returns_true(self):
        from bot.handlers.other import check_sub_channel
        member = MagicMock()
        member.status = ChatMemberStatus.MEMBER
        assert await check_sub_channel(member) is True

    @pytest.mark.asyncio
    async def test_administrator_returns_true(self):
        from bot.handlers.other import check_sub_channel
        member = MagicMock()
        member.status = ChatMemberStatus.ADMINISTRATOR
        assert await check_sub_channel(member) is True

    @pytest.mark.asyncio
    async def test_creator_returns_true(self):
        from bot.handlers.other import check_sub_channel
        member = MagicMock()
        member.status = ChatMemberStatus.CREATOR
        assert await check_sub_channel(member) is True

    @pytest.mark.asyncio
    async def test_left_returns_false(self):
        from bot.handlers.other import check_sub_channel
        member = MagicMock()
        member.status = ChatMemberStatus.LEFT
        assert await check_sub_channel(member) is False

    @pytest.mark.asyncio
    async def test_kicked_returns_false(self):
        from bot.handlers.other import check_sub_channel
        member = MagicMock()
        member.status = ChatMemberStatus.KICKED
        assert await check_sub_channel(member) is False


class TestAnyPaymentMethodEnabled:

    def test_all_enabled(self):
        from bot.handlers.other import _any_payment_method_enabled
        with patch('bot.handlers.other.EnvKeys') as env:
            env.CRYPTO_PAY_TOKEN = "token"
            env.STARS_PER_VALUE = 0.91
            env.TELEGRAM_PROVIDER_TOKEN = "provider"
            assert _any_payment_method_enabled() is True

    def test_none_enabled(self):
        from bot.handlers.other import _any_payment_method_enabled
        with patch('bot.handlers.other.EnvKeys') as env:
            env.CRYPTO_PAY_TOKEN = ""
            env.STARS_PER_VALUE = 0
            env.TELEGRAM_PROVIDER_TOKEN = ""
            assert _any_payment_method_enabled() is False

    def test_only_crypto_enabled(self):
        from bot.handlers.other import _any_payment_method_enabled
        with patch('bot.handlers.other.EnvKeys') as env:
            env.CRYPTO_PAY_TOKEN = "token"
            env.STARS_PER_VALUE = 0
            env.TELEGRAM_PROVIDER_TOKEN = ""
            assert _any_payment_method_enabled() is True

    def test_only_stars_enabled(self):
        from bot.handlers.other import _any_payment_method_enabled
        with patch('bot.handlers.other.EnvKeys') as env:
            env.CRYPTO_PAY_TOKEN = ""
            env.STARS_PER_VALUE = 0.91
            env.TELEGRAM_PROVIDER_TOKEN = ""
            assert _any_payment_method_enabled() is True


class TestGenerateShortHash:

    def test_deterministic(self):
        from bot.handlers.other import generate_short_hash
        h1 = generate_short_hash("test")
        h2 = generate_short_hash("test")
        assert h1 == h2

    def test_correct_length(self):
        from bot.handlers.other import generate_short_hash
        assert len(generate_short_hash("test")) == 8
        assert len(generate_short_hash("test", length=12)) == 12

    def test_different_inputs_different_hashes(self):
        from bot.handlers.other import generate_short_hash
        h1 = generate_short_hash("hello")
        h2 = generate_short_hash("world")
        assert h1 != h2


class TestIsSafeItemName:

    def test_valid_name(self):
        from bot.handlers.other import is_safe_item_name
        assert is_safe_item_name("Normal Product") is True

    def test_valid_unicode(self):
        from bot.handlers.other import is_safe_item_name
        assert is_safe_item_name("Товар 🎮") is True

    def test_empty_string(self):
        from bot.handlers.other import is_safe_item_name
        assert is_safe_item_name("") is False

    def test_too_long(self):
        from bot.handlers.other import is_safe_item_name
        assert is_safe_item_name("A" * 101) is False

    def test_exactly_100_chars(self):
        from bot.handlers.other import is_safe_item_name
        assert is_safe_item_name("A" * 100) is True

    def test_control_characters(self):
        from bot.handlers.other import is_safe_item_name
        assert is_safe_item_name("item\x00name") is False
        assert is_safe_item_name("item\x1fname") is False
        assert is_safe_item_name("item\x7fname") is False

    def test_single_char(self):
        from bot.handlers.other import is_safe_item_name
        assert is_safe_item_name("A") is True
