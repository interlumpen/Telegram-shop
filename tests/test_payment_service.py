import pytest
import math
from unittest.mock import patch, AsyncMock, MagicMock

from bot.misc.services.payment import (
    currency_to_stars,
    _minor_units_for,
    send_stars_invoice,
    send_fiat_invoice,
    CryptoPayAPI,
    CryptoPayAPIError,
)


class TestCurrencyToStars:

    @pytest.mark.parametrize("rate,amount,expected", [
        (0.91, 100, 91),
        (0.33, 10, 4),        # 3.3 rounds up
        (0.91, 0, 0),
        (0.91, 100000, math.ceil(100000 * 0.91)),
        (1.0, 50, 50),        # already integral
    ])
    def test_conversion(self, rate, amount, expected):
        with patch('bot.misc.services.payment.EnvKeys') as env:
            env.STARS_PER_VALUE = rate
            assert currency_to_stars(amount) == expected


class TestMinorUnitsFor:

    @pytest.mark.parametrize("currency,expected", [
        ("USD", 100),
        ("RUB", 100),
        ("EUR", 100),
        ("JPY", 1),   # zero-decimal currency
        ("KRW", 1),
        ("jpy", 1),   # lookup is case-insensitive
        ("usd", 100),
    ])
    def test_minor_units(self, currency, expected):
        assert _minor_units_for(currency) == expected


class TestSendStarsInvoice:

    async def test_sends_correct_invoice(self):
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

    async def test_stars_price_amount(self):
        bot = AsyncMock()

        with patch('bot.misc.services.payment.EnvKeys') as env:
            env.STARS_PER_VALUE = 0.91
            env.PAY_CURRENCY = "RUB"
            await send_stars_invoice(bot, chat_id=123, amount=100)

        prices = bot.send_invoice.call_args[1]['prices']
        assert prices[0].amount == math.ceil(100 * 0.91)


class TestSendFiatInvoice:

    async def test_sends_correct_invoice(self):
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

    async def test_zero_decimal_currency(self):
        bot = AsyncMock()

        with patch('bot.misc.services.payment.EnvKeys') as env:
            env.TELEGRAM_PROVIDER_TOKEN = "test_token"
            env.PAY_CURRENCY = "JPY"
            await send_fiat_invoice(bot=bot, chat_id=456, amount=200)

        prices = bot.send_invoice.call_args[1]['prices']
        # JPY has no minor units: 200 * 1 = 200
        assert prices[0].amount == 200

    async def test_missing_provider_token_raises(self):
        bot = AsyncMock()

        with patch('bot.misc.services.payment.EnvKeys') as env:
            env.TELEGRAM_PROVIDER_TOKEN = ""
            with pytest.raises(RuntimeError, match="TELEGRAM_PROVIDER_TOKEN"):
                await send_fiat_invoice(bot=bot, chat_id=456, amount=200)


class TestCryptoPayAPI:

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
