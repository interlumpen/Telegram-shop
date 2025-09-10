import pytest
from decimal import Decimal
from pydantic import ValidationError

from bot.misc import (
    PaymentRequest, ItemPurchaseRequest, UserDataUpdate,
    CategoryRequest, BroadcastMessage, SearchQuery,
    validate_telegram_id, validate_money_amount, sanitize_html
)


class TestValidators:
    """Test suite for data validators"""

    def test_payment_request_validation(self):
        """Test payment request validation"""
        # Valid request
        valid_request = PaymentRequest(
            amount=Decimal("100.50"),
            currency="USD",
            provider="telegram"
        )
        assert valid_request.amount == Decimal("100.50")
        assert valid_request.currency == "USD"

        # Invalid amount (negative)
        with pytest.raises(ValidationError):
            PaymentRequest(
                amount=Decimal("-10"),
                currency="USD",
                provider="telegram"
            )

        # Invalid amount (too many decimal places)
        with pytest.raises(ValidationError):
            PaymentRequest(
                amount=Decimal("100.123"),
                currency="USD",
                provider="telegram"
            )

        # Invalid currency (wrong length)
        with pytest.raises(ValidationError):
            PaymentRequest(
                amount=Decimal("100"),
                currency="USDD",
                provider="telegram"
            )

        # Invalid provider
        with pytest.raises(ValidationError):
            PaymentRequest(
                amount=Decimal("100"),
                currency="USD",
                provider="invalid_provider"
            )

    def test_item_purchase_request_validation(self):
        """Test item purchase request validation"""
        # Valid request
        valid_request = ItemPurchaseRequest(
            item_name="Valid Item Name",
            user_id=123456
        )
        assert valid_request.item_name == "Valid Item Name"
        assert valid_request.user_id == 123456

        # SQL injection attempt
        with pytest.raises(ValidationError):
            ItemPurchaseRequest(
                item_name="'; DROP TABLE users; --",
                user_id=123456
            )

        # XSS attempt
        with pytest.raises(ValidationError):
            ItemPurchaseRequest(
                item_name="<script>alert('xss')</script>",
                user_id=123456
            )

        # Invalid user_id
        with pytest.raises(ValidationError):
            ItemPurchaseRequest(
                item_name="Valid Item",
                user_id=-1
            )

    def test_user_data_update_validation(self):
        """Test user data update validation"""
        # Valid update
        valid_update = UserDataUpdate(
            telegram_id=123456,
            balance=Decimal("100.00")
        )
        assert valid_update.telegram_id == 123456
        assert valid_update.balance == Decimal("100.00")

        # Invalid telegram_id
        with pytest.raises(ValidationError):
            UserDataUpdate(
                telegram_id=-1,
                balance=Decimal("100")
            )

        # Invalid balance (negative)
        with pytest.raises(ValidationError):
            UserDataUpdate(
                telegram_id=123456,
                balance=Decimal("-100")
            )

        # Valid with None balance
        valid_none = UserDataUpdate(
            telegram_id=123456,
            balance=None
        )
        assert valid_none.balance is None

    def test_category_request_validation(self):
        """Test category request validation"""
        # Valid request
        valid_request = CategoryRequest(name="Valid Category")
        assert valid_request.name == "Valid Category"
        assert valid_request.sanitize_name() == "Valid Category"

        # HTML tags removal
        html_request = CategoryRequest(name="<b>Bold</b> Category")
        assert html_request.sanitize_name() == "Bold Category"

        # Multiple spaces normalization
        spaces_request = CategoryRequest(name="Category    With    Spaces")
        assert spaces_request.sanitize_name() == "Category With Spaces"

        # Empty name should fail
        with pytest.raises(ValidationError):
            CategoryRequest(name="")

    def test_broadcast_message_validation(self):
        """Test broadcast message validation"""
        # Valid HTML message
        valid_html = BroadcastMessage(
            text="<b>Bold</b> text",
            parse_mode="HTML"
        )
        assert valid_html.text == "<b>Bold</b> text"

        # Invalid HTML (unbalanced tags) - more explicit tag
        with pytest.raises(ValidationError) as exc_info:
            BroadcastMessage(
                text="<b>Unclosed bold tag",  # More clear unbalanced tag
                parse_mode="HTML"
            )
        assert "Unbalanced HTML tag" in str(exc_info.value)

        # Test with attributes
        with pytest.raises(ValidationError):
            BroadcastMessage(
                text='<a href="test">Link',  # Unclosed anchor with attribute
                parse_mode="HTML"
            )

        # Valid Markdown
        valid_md = BroadcastMessage(
            text="*Bold* text",
            parse_mode="Markdown"
        )
        assert valid_md.parse_mode == "Markdown"

        # Invalid parse mode
        with pytest.raises(ValidationError):
            BroadcastMessage(
                text="Text",
                parse_mode="InvalidMode"
            )

        # Empty text
        with pytest.raises(ValidationError):
            BroadcastMessage(text="")

        # Too long text
        with pytest.raises(ValidationError):
            BroadcastMessage(text="x" * 4097)

    def test_search_query_validation(self):
        """Test search query validation"""
        # Valid query
        valid_query = SearchQuery(query="search term", limit=50)
        assert valid_query.query == "search term"
        assert valid_query.limit == 50

        # Sanitization
        special_query = SearchQuery(query="search@#$%term")
        assert "searchterm" in special_query.sanitize_query(special_query.query)

        # Invalid limit (too high)
        with pytest.raises(ValidationError):
            SearchQuery(query="search", limit=101)

        # Invalid limit (too low)
        with pytest.raises(ValidationError):
            SearchQuery(query="search", limit=0)

        # Empty query
        with pytest.raises(ValidationError):
            SearchQuery(query="")

    def test_telegram_id_validation(self):
        """Test telegram ID validation"""
        # Valid ID
        assert validate_telegram_id("123456") == 123456
        assert validate_telegram_id(789012) == 789012

        # Invalid IDs
        with pytest.raises(ValueError):
            validate_telegram_id("-1")

        with pytest.raises(ValueError):
            validate_telegram_id("0")

        with pytest.raises(ValueError):
            validate_telegram_id("99999999999")  # Too large

        with pytest.raises(ValueError):
            validate_telegram_id("not_a_number")

        with pytest.raises(ValueError):
            validate_telegram_id(None)

    def test_money_amount_validation(self):
        """Test money amount validation"""
        # Valid amounts
        assert validate_money_amount("100") == Decimal("100.00")
        assert validate_money_amount("100.50") == Decimal("100.50")
        assert validate_money_amount(Decimal("99.99")) == Decimal("99.99")

        # With custom limits
        assert validate_money_amount(
            "5",
            min_amount=Decimal("1"),
            max_amount=Decimal("10")
        ) == Decimal("5.00")

        # Invalid amounts
        with pytest.raises(ValueError):
            validate_money_amount("0")  # Below default minimum

        with pytest.raises(ValueError):
            validate_money_amount("1000001")  # Above default maximum

        with pytest.raises(ValueError):
            validate_money_amount("-100")  # Negative

        with pytest.raises(ValueError):
            validate_money_amount("not_a_number")

        # Rounding test
        assert validate_money_amount("100.999") == Decimal("101.00")
        assert validate_money_amount("100.001") == Decimal("100.00")

    def test_sanitize_html(self):
        """Test HTML sanitization"""
        # Basic escaping
        assert sanitize_html("Test & test") == "Test &amp; test"
        assert sanitize_html("1 < 2") == "1 &lt; 2"
        assert sanitize_html("2 > 1") == "2 &gt; 1"
        assert sanitize_html('"Quote"') == '&quot;Quote&quot;'
        assert sanitize_html("'Quote'") == '&#39;Quote&#39;'

        # Safe tags preservation
        assert sanitize_html("<b>Bold</b>") == "<b>Bold</b>"
        assert sanitize_html("<i>Italic</i>") == "<i>Italic</i>"
        assert sanitize_html("<u>Underline</u>") == "<u>Underline</u>"
        assert sanitize_html("<code>Code</code>") == "<code>Code</code>"

        # Dangerous tags escaping
        assert "&lt;script&gt;" in sanitize_html("<script>alert('xss')</script>")
        assert "&lt;img" in sanitize_html("<img src=x onerror=alert('xss')>")

        # Mixed content
        mixed = "<b>Safe</b> & <script>Dangerous</script>"
        result = sanitize_html(mixed)
        assert "<b>Safe</b>" in result
        assert "&lt;script&gt;" in result

    def test_edge_cases(self):
        """Test edge cases in validation"""
        # Very long but valid item name
        long_name = "A" * 100
        request = ItemPurchaseRequest(item_name=long_name, user_id=123)
        assert len(request.item_name) == 100

        # Item name with unicode characters
        unicode_name = "Товар 商品 📦"
        unicode_request = ItemPurchaseRequest(item_name=unicode_name, user_id=123)
        assert unicode_request.item_name == unicode_name

        # Boundary value for payment amount
        max_payment = PaymentRequest(
            amount=Decimal("100000"),
            currency="USD",
            provider="telegram"
        )
        assert max_payment.amount == Decimal("100000")

        # Minimum valid payment
        min_payment = PaymentRequest(
            amount=Decimal("0.01"),
            currency="USD",
            provider="telegram"
        )
        assert min_payment.amount == Decimal("0.01")
