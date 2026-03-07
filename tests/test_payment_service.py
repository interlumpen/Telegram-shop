import pytest
import math
from unittest.mock import patch, AsyncMock, MagicMock

from bot.misc.services.payment import (
    currency_to_stars,
    _minor_units_for,
    CryptoPayAPI,
    CryptoPayAPIError,
)


class TestCurrencyToStars:

    def test_basic_conversion(self):
        with patch('bot.misc.services.payment.EnvKeys') as env:
            env.STARS_PER_VALUE = 0.91
            result = currency_to_stars(100)
        assert result == math.ceil(100 * 0.91)
        assert result == 91

    def test_rounds_up(self):
        with patch('bot.misc.services.payment.EnvKeys') as env:
            env.STARS_PER_VALUE = 0.33
            result = currency_to_stars(10)
        # 10 * 0.33 = 3.3 -> ceil = 4
        assert result == 4

    def test_zero_amount(self):
        with patch('bot.misc.services.payment.EnvKeys') as env:
            env.STARS_PER_VALUE = 0.91
            result = currency_to_stars(0)
        assert result == 0

    def test_large_amount(self):
        with patch('bot.misc.services.payment.EnvKeys') as env:
            env.STARS_PER_VALUE = 0.91
            result = currency_to_stars(100000)
        assert result == math.ceil(100000 * 0.91)

    def test_exact_integer_result(self):
        with patch('bot.misc.services.payment.EnvKeys') as env:
            env.STARS_PER_VALUE = 1.0
            result = currency_to_stars(50)
        assert result == 50


class TestMinorUnitsFor:

    def test_regular_currency_usd(self):
        assert _minor_units_for("USD") == 100

    def test_regular_currency_rub(self):
        assert _minor_units_for("RUB") == 100

    def test_regular_currency_eur(self):
        assert _minor_units_for("EUR") == 100

    def test_zero_decimal_jpy(self):
        assert _minor_units_for("JPY") == 1

    def test_zero_decimal_krw(self):
        assert _minor_units_for("KRW") == 1

    def test_case_insensitive(self):
        assert _minor_units_for("jpy") == 1
        assert _minor_units_for("usd") == 100


class TestSendStarsInvoice:

    @pytest.mark.asyncio
    async def test_sends_correct_invoice(self):
        from bot.misc.services.payment import send_stars_invoice

        bot = AsyncMock()

        with patch('bot.misc.services.payment.EnvKeys') as env:
            env.STARS_PER_VALUE = 0.91
            env.PAY_CURRENCY = "RUB"
            await send_stars_invoice(bot, chat_id=123, amount=100)

        bot.send_invoice.assert_called_once()
        call_kwargs = bot.send_invoice.call_args[1]
        assert call_kwargs['currency'] == "XTR"
        assert call_kwargs['provider_token'] == ""
        assert call_kwargs['chat_id'] == 123

    @pytest.mark.asyncio
    async def test_stars_price_amount(self):
        from bot.misc.services.payment import send_stars_invoice

        bot = AsyncMock()

        with patch('bot.misc.services.payment.EnvKeys') as env:
            env.STARS_PER_VALUE = 0.91
            env.PAY_CURRENCY = "RUB"
            await send_stars_invoice(bot, chat_id=123, amount=100)

        prices = bot.send_invoice.call_args[1]['prices']
        assert prices[0].amount == math.ceil(100 * 0.91)


class TestSendFiatInvoice:

    @pytest.mark.asyncio
    async def test_sends_correct_invoice(self):
        from bot.misc.services.payment import send_fiat_invoice

        bot = AsyncMock()

        with patch('bot.misc.services.payment.EnvKeys') as env:
            env.TELEGRAM_PROVIDER_TOKEN = "test_token"
            env.PAY_CURRENCY = "RUB"
            await send_fiat_invoice(bot=bot, chat_id=456, amount=200)

        bot.send_invoice.assert_called_once()
        call_kwargs = bot.send_invoice.call_args[1]
        assert call_kwargs['currency'] == "RUB"
        assert call_kwargs['provider_token'] == "test_token"
        # RUB has minor units: 200 * 100 = 20000
        assert call_kwargs['prices'][0].amount == 20000

    @pytest.mark.asyncio
    async def test_zero_decimal_currency(self):
        from bot.misc.services.payment import send_fiat_invoice

        bot = AsyncMock()

        with patch('bot.misc.services.payment.EnvKeys') as env:
            env.TELEGRAM_PROVIDER_TOKEN = "test_token"
            env.PAY_CURRENCY = "JPY"
            await send_fiat_invoice(bot=bot, chat_id=456, amount=200)

        prices = bot.send_invoice.call_args[1]['prices']
        # JPY has no minor units: 200 * 1 = 200
        assert prices[0].amount == 200

    @pytest.mark.asyncio
    async def test_missing_provider_token_raises(self):
        from bot.misc.services.payment import send_fiat_invoice

        bot = AsyncMock()

        with patch('bot.misc.services.payment.EnvKeys') as env:
            env.TELEGRAM_PROVIDER_TOKEN = ""
            with pytest.raises(RuntimeError, match="TELEGRAM_PROVIDER_TOKEN"):
                await send_fiat_invoice(bot=bot, chat_id=456, amount=200)


class TestCryptoPayAPI:

    @pytest.mark.asyncio
    async def test_api_error_raises(self):
        api = CryptoPayAPI()

        mock_response = AsyncMock()
        mock_response.json = AsyncMock(return_value={
            "ok": False,
            "error": {"code": 400, "name": "INVALID_PARAMS"}
        })
        mock_response.raise_for_status = MagicMock()
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.post = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch('aiohttp.ClientSession', return_value=mock_session):
            with pytest.raises(CryptoPayAPIError) as exc_info:
                await api.create_invoice(amount=100, expires_in=1800)
            assert exc_info.value.code == 400
            assert exc_info.value.name == "INVALID_PARAMS"

    def test_crypto_pay_api_error_str(self):
        err = CryptoPayAPIError(code=401, name="UNAUTHORIZED")
        assert "401" in str(err)
        assert "UNAUTHORIZED" in str(err)
