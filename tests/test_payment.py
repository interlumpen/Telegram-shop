import pytest
import json
from unittest.mock import MagicMock, AsyncMock, patch
from decimal import Decimal
from aiogram.types import LabeledPrice

from bot.misc.payment import (
    currency_to_stars, send_stars_invoice, send_fiat_invoice,
    _minor_units_for, CryptoPayAPI, ZERO_DEC_CURRENCIES
)
from bot.misc import EnvKeys


class TestPaymentModule:
    """Test suite for payment functionality"""

    def test_currency_to_stars_conversion(self):
        """Test currency to Telegram Stars conversion"""
        # Mock STARS_PER_VALUE
        with patch.object(EnvKeys, 'STARS_PER_VALUE', 0.1):
            assert currency_to_stars(100) == 10  # 100 * 0.1 = 10
            assert currency_to_stars(150) == 15  # 150 * 0.1 = 15
            assert currency_to_stars(1) == 1  # 1 * 0.1 = 0.1, ceil to 1
            assert currency_to_stars(0) == 0  # 0 * 0.1 = 0

        # Test rounding up behavior
        with patch.object(EnvKeys, 'STARS_PER_VALUE', 0.03):
            assert currency_to_stars(100) == 3  # 100 * 0.03 = 3.0
            assert currency_to_stars(101) == 4  # 101 * 0.03 = 3.03, ceil to 4
            assert currency_to_stars(33) == 1  # 33 * 0.03 = 0.99, ceil to 1

    def test_minor_units_for_currency(self):
        """Test minor units calculation for different currencies"""
        # Currencies with cents/decimals
        assert _minor_units_for("USD") == 100
        assert _minor_units_for("EUR") == 100
        assert _minor_units_for("RUB") == 100
        assert _minor_units_for("usd") == 100  # Case insensitive

        # Currencies without minor units
        assert _minor_units_for("JPY") == 1
        assert _minor_units_for("KRW") == 1
        assert _minor_units_for("jpy") == 1  # Case insensitive

    @pytest.mark.asyncio
    async def test_send_stars_invoice(self):
        """Test sending Telegram Stars invoice"""
        bot = AsyncMock()
        chat_id = 12345
        amount = 100

        with patch.object(EnvKeys, 'STARS_PER_VALUE', 0.1):
            with patch.object(EnvKeys, 'PAY_CURRENCY', 'RUB'):
                with patch('bot.misc.payment.localize') as mock_localize:
                    # Mock localization strings
                    mock_localize.side_effect = lambda key, **kwargs: f"mocked_{key}"

                    await send_stars_invoice(
                        bot=bot,
                        chat_id=chat_id,
                        amount=amount,
                        title="Test Title",
                        description="Test Description"
                    )

                    # Verify bot.send_invoice was called correctly
                    bot.send_invoice.assert_called_once()
                    call_args = bot.send_invoice.call_args[1]

                    assert call_args['chat_id'] == chat_id
                    assert call_args['title'] == "Test Title"
                    assert call_args['description'] == "Test Description"
                    assert call_args['provider_token'] == ""
                    assert call_args['currency'] == "XTR"

                    # Check prices
                    prices = call_args['prices']
                    assert len(prices) == 1
                    assert prices[0].amount == 10  # 100 * 0.1 = 10 stars

                    # Check payload
                    payload = json.loads(call_args['payload'])
                    assert payload['op'] == "topup_balance_stars"
                    assert payload['amount_rub'] == 100
                    assert payload['stars'] == 10

    @pytest.mark.asyncio
    async def test_send_stars_invoice_with_payload_extra(self):
        """Test sending Stars invoice with extra payload data"""
        bot = AsyncMock()
        payload_extra = {"user_id": 999, "referrer": "friend"}

        with patch.object(EnvKeys, 'STARS_PER_VALUE', 0.2):
            with patch('bot.misc.payment.localize') as mock_localize:
                mock_localize.return_value = "mocked"

                await send_stars_invoice(
                    bot=bot,
                    chat_id=12345,
                    amount=50,
                    payload_extra=payload_extra
                )

                call_args = bot.send_invoice.call_args[1]
                payload = json.loads(call_args['payload'])

                # Check extra payload was included
                assert payload['user_id'] == 999
                assert payload['referrer'] == "friend"
                assert payload['op'] == "topup_balance_stars"

    @pytest.mark.asyncio
    async def test_send_fiat_invoice(self):
        """Test sending fiat invoice via Telegram Payments"""
        bot = AsyncMock()
        chat_id = 12345
        amount = 250

        with patch.object(EnvKeys, 'TELEGRAM_PROVIDER_TOKEN', 'test_token'):
            with patch.object(EnvKeys, 'PAY_CURRENCY', 'USD'):
                with patch('bot.misc.payment.localize') as mock_localize:
                    mock_localize.side_effect = lambda key, **kwargs: f"mocked_{key}"

                    await send_fiat_invoice(
                        bot=bot,
                        chat_id=chat_id,
                        amount=amount,
                        title="Fiat Payment",
                        description="Test fiat payment"
                    )

                    bot.send_invoice.assert_called_once()
                    call_args = bot.send_invoice.call_args[1]

                    assert call_args['chat_id'] == chat_id
                    assert call_args['title'] == "Fiat Payment"
                    assert call_args['description'] == "Test fiat payment"
                    assert call_args['provider_token'] == 'test_token'
                    assert call_args['currency'] == 'USD'
                    assert call_args['request_timeout'] == 60

                    # Check price conversion (USD has 100 minor units)
                    prices = call_args['prices']
                    assert len(prices) == 1
                    assert prices[0].amount == 25000  # 250 * 100

                    # Check payload
                    payload = json.loads(call_args['payload'])
                    assert payload['type'] == "balance_topup"
                    assert payload['amount'] == 250

    @pytest.mark.asyncio
    async def test_send_fiat_invoice_no_provider_token(self):
        """Test sending fiat invoice without provider token raises error"""
        bot = AsyncMock()

        with patch.object(EnvKeys, 'TELEGRAM_PROVIDER_TOKEN', None):
            with pytest.raises(RuntimeError, match="TELEGRAM_PROVIDER_TOKEN is not set"):
                await send_fiat_invoice(
                    bot=bot,
                    chat_id=12345,
                    amount=100
                )

    @pytest.mark.asyncio
    async def test_send_fiat_invoice_jpy_currency(self):
        """Test fiat invoice with JPY (no minor units)"""
        bot = AsyncMock()

        with patch.object(EnvKeys, 'TELEGRAM_PROVIDER_TOKEN', 'test_token'):
            with patch.object(EnvKeys, 'PAY_CURRENCY', 'JPY'):
                with patch('bot.misc.payment.localize') as mock_localize:
                    mock_localize.return_value = "mocked"

                    await send_fiat_invoice(
                        bot=bot,
                        chat_id=12345,
                        amount=1000
                    )

                    call_args = bot.send_invoice.call_args[1]
                    assert call_args['currency'] == 'JPY'

                    # JPY has no minor units, so amount should be 1000 * 1 = 1000
                    prices = call_args['prices']
                    assert prices[0].amount == 1000


class TestCryptoPayAPI:
    """Test suite for CryptoPay API client"""

    def test_crypto_pay_api_initialization(self):
        """Test CryptoPay API client initialization"""
        with patch.object(EnvKeys, 'CRYPTO_PAY_TOKEN', 'test_crypto_token'):
            api = CryptoPayAPI()
            assert api.token == 'test_crypto_token'
            assert api.base_url == "https://pay.crypt.bot/api"

    @pytest.mark.asyncio
    async def test_crypto_pay_create_invoice(self):
        """Test creating CryptoPay invoice"""
        with patch.object(EnvKeys, 'CRYPTO_PAY_TOKEN', 'test_token'):
            with patch.object(EnvKeys, 'PAY_CURRENCY', 'USD'):
                api = CryptoPayAPI()

                mock_response = {
                    "result": {
                        "invoice_id": "INV123",
                        "hash": "abc123",
                        "mini_app_invoice_url": "https://example.com/invoice",
                        "web_app_invoice_url": "https://example.com/webapp"
                    }
                }

                with patch('bot.misc.payment.aiohttp.ClientSession') as mock_session_class:
                    # Create a mock response
                    class MockResponse:
                        async def json(self):
                            return mock_response

                        def raise_for_status(self):
                            pass

                    # Create a mock context manager for post
                    class MockContext:
                        async def __aenter__(self):
                            return MockResponse()

                        async def __aexit__(self, *args):
                            pass

                    # Create session that returns our mock context and tracks calls
                    mock_session_instance = MagicMock()
                    mock_session_instance.post = MagicMock(return_value=MockContext())
                    mock_session_instance.__aenter__ = AsyncMock(return_value=mock_session_instance)
                    mock_session_instance.__aexit__ = AsyncMock(return_value=None)
                    mock_session_class.return_value = mock_session_instance

                    result = await api.create_invoice(
                        amount=100.50,
                        expires_in=3600,
                        currency="USD",
                        accepted_assets="TON,USDT",
                        payload="test_payload",
                        description="Test invoice"
                    )

                    assert result["invoice_id"] == "INV123"
                    assert result["hash"] == "abc123"

                    # Verify request parameters
                    mock_session_instance.post.assert_called_once()
                    call_args = mock_session_instance.post.call_args

                    # Check URL
                    assert call_args[0][0] == "https://pay.crypt.bot/api/createInvoice"

                    # Check headers
                    headers = call_args[1]['headers']
                    assert headers['Crypto-Pay-API-Token'] == 'test_token'

                    # Check request data
                    json_data = call_args[1]['json']
                    assert json_data['currency_type'] == 'fiat'
                    assert json_data['fiat'] == 'USD'
                    assert json_data['amount'] == '100.5'
                    assert json_data['accepted_assets'] == 'TON,USDT'
                    assert json_data['payload'] == 'test_payload'
                    assert json_data['description'] == 'Test invoice'
                    assert json_data['expires_in'] == 3600

    @pytest.mark.asyncio
    async def test_crypto_pay_get_invoice(self):
        """Test fetching CryptoPay invoice"""
        with patch.object(EnvKeys, 'CRYPTO_PAY_TOKEN', 'test_token'):
            api = CryptoPayAPI()

            mock_response = {
                "result": {
                    "items": [{
                        "invoice_id": "INV123",
                        "hash": "abc123",
                        "status": "paid",
                        "amount": "100.50"
                    }]
                }
            }

            with patch('bot.misc.payment.aiohttp.ClientSession') as mock_session_class:
                # Create a mock response
                class MockResponse:
                    async def json(self):
                        return mock_response

                    def raise_for_status(self):
                        pass

                # Create a mock context manager for get
                class MockContext:
                    async def __aenter__(self):
                        return MockResponse()

                    async def __aexit__(self, *args):
                        pass

                # Create session that returns our mock context and tracks calls
                mock_session_instance = MagicMock()
                mock_session_instance.get = MagicMock(return_value=MockContext())
                mock_session_instance.__aenter__ = AsyncMock(return_value=mock_session_instance)
                mock_session_instance.__aexit__ = AsyncMock(return_value=None)
                mock_session_class.return_value = mock_session_instance

                result = await api.get_invoice("INV123")

                assert result["invoice_id"] == "INV123"
                assert result["status"] == "paid"

                # Verify GET request
                mock_session_instance.get.assert_called_once()
                call_args = mock_session_instance.get.call_args

                assert call_args[0][0] == "https://pay.crypt.bot/api/getInvoices"
                assert call_args[1]['params'] == {"invoice_ids": "INV123"}

    @pytest.mark.asyncio
    async def test_crypto_pay_get_invoice_empty_result(self):
        """Test fetching non-existent CryptoPay invoice"""
        with patch.object(EnvKeys, 'CRYPTO_PAY_TOKEN', 'test_token'):
            api = CryptoPayAPI()

            mock_response = {
                "result": {
                    "items": []
                }
            }

            with patch('bot.misc.payment.aiohttp.ClientSession') as mock_session_class:
                # Create a mock response
                class MockResponse:
                    async def json(self):
                        return mock_response

                    def raise_for_status(self):
                        pass

                # Create a mock context manager for get
                class MockContext:
                    async def __aenter__(self):
                        return MockResponse()

                    async def __aexit__(self, *args):
                        pass

                # Create session that returns our mock context and tracks calls
                mock_session_instance = MagicMock()
                mock_session_instance.get = MagicMock(return_value=MockContext())
                mock_session_instance.__aenter__ = AsyncMock(return_value=mock_session_instance)
                mock_session_instance.__aexit__ = AsyncMock(return_value=None)
                mock_session_class.return_value = mock_session_instance

                result = await api.get_invoice("NONEXISTENT")

                assert result == {}

    @pytest.mark.asyncio
    async def test_crypto_pay_api_error_handling(self):
        """Test CryptoPay API error handling"""
        with patch.object(EnvKeys, 'CRYPTO_PAY_TOKEN', 'test_token'):
            api = CryptoPayAPI()

            with patch('aiohttp.ClientSession') as mock_session:
                # Create proper async context manager classes
                class MockResponse:
                    def raise_for_status(self):
                        raise Exception("HTTP 500 Error")

                class MockPostContext:
                    async def __aenter__(self):
                        return MockResponse()

                    async def __aexit__(self, *args):
                        pass

                class MockSession:
                    def post(self, url, json=None, headers=None):
                        return MockPostContext()

                    async def __aenter__(self):
                        return self

                    async def __aexit__(self, *args):
                        pass

                mock_session.return_value = MockSession()

                with pytest.raises(Exception, match="HTTP 500 Error"):
                    await api.create_invoice(amount=100, expires_in=3600)

    def test_zero_dec_currencies_constant(self):
        """Test ZERO_DEC_CURRENCIES constant"""
        assert "JPY" in ZERO_DEC_CURRENCIES
        assert "KRW" in ZERO_DEC_CURRENCIES
        assert "USD" not in ZERO_DEC_CURRENCIES
        assert "EUR" not in ZERO_DEC_CURRENCIES

    @pytest.mark.asyncio
    async def test_crypto_pay_request_method_routing(self):
        """Test that GET methods use GET requests and others use POST"""
        with patch.object(EnvKeys, 'CRYPTO_PAY_TOKEN', 'test_token'):
            api = CryptoPayAPI()

            # Test GET method
            with patch('aiohttp.ClientSession') as mock_session:
                # Create proper async context manager classes
                class MockGetResponse:
                    async def json(self):
                        return {"result": {"items": []}}

                    def raise_for_status(self):
                        pass

                class MockGetContext:
                    async def __aenter__(self):
                        return MockGetResponse()

                    async def __aexit__(self, *args):
                        pass

                class MockGetSession:
                    def __init__(self):
                        self.get_called = False
                        self.post_called = False

                    def get(self, url, params=None, headers=None):
                        self.get_called = True
                        return MockGetContext()

                    def post(self, url, json=None, headers=None):
                        self.post_called = True
                        return None

                    async def __aenter__(self):
                        return self

                    async def __aexit__(self, *args):
                        pass

                mock_get_session = MockGetSession()
                mock_session.return_value = mock_get_session

                await api._request("getInvoices", {"invoice_ids": "test"})

                # Should use GET
                assert mock_get_session.get_called
                assert not mock_get_session.post_called

            # Test POST method
            with patch('aiohttp.ClientSession') as mock_session:
                # Create proper async context manager classes
                class MockPostResponse:
                    async def json(self):
                        return {"result": {}}

                    def raise_for_status(self):
                        pass

                class MockPostContext:
                    async def __aenter__(self):
                        return MockPostResponse()

                    async def __aexit__(self, *args):
                        pass

                class MockPostSession:
                    def __init__(self):
                        self.get_called = False
                        self.post_called = False

                    def get(self, url, params=None, headers=None):
                        self.get_called = True
                        return None

                    def post(self, url, json=None, headers=None):
                        self.post_called = True
                        return MockPostContext()

                    async def __aenter__(self):
                        return self

                    async def __aexit__(self, *args):
                        pass

                mock_post_session = MockPostSession()
                mock_session.return_value = mock_post_session

                await api._request("createInvoice", {"amount": "100"})

                # Should use POST
                assert mock_post_session.post_called
                assert not mock_post_session.get_called
