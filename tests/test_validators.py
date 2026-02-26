import pytest
from decimal import Decimal
from pydantic import ValidationError

from bot.misc.validators import validate_telegram_id, validate_money_amount, sanitize_html, PaymentRequest, \
    ItemPurchaseRequest, CategoryRequest, BroadcastMessage


class TestValidateTelegramId:

    def test_valid_id(self):
        assert validate_telegram_id(12345) == 12345

    def test_valid_id_large(self):
        assert validate_telegram_id(9999999999) == 9999999999

    def test_string_id(self):
        assert validate_telegram_id("12345") == 12345

    def test_zero_raises(self):
        with pytest.raises(ValueError):
            validate_telegram_id(0)

    def test_negative_raises(self):
        with pytest.raises(ValueError):
            validate_telegram_id(-1)

    def test_too_large_raises(self):
        with pytest.raises(ValueError):
            validate_telegram_id(10000000000)

    def test_non_numeric_raises(self):
        with pytest.raises(ValueError):
            validate_telegram_id("abc")

    def test_none_raises(self):
        with pytest.raises(ValueError):
            validate_telegram_id(None)


class TestValidateMoneyAmount:

    def test_valid_amount(self):
        result = validate_money_amount("50")
        assert result == Decimal("50.00")

    def test_valid_decimal(self):
        result = validate_money_amount("99.99")
        assert result == Decimal("99.99")

    def test_below_min_raises(self):
        with pytest.raises(ValueError):
            validate_money_amount("0.001", min_amount=Decimal("0.01"))

    def test_above_max_raises(self):
        with pytest.raises(ValueError):
            validate_money_amount("2000000", max_amount=Decimal("1000000"))

    def test_non_numeric_raises(self):
        with pytest.raises(ValueError):
            validate_money_amount("abc")

    def test_negative_raises(self):
        with pytest.raises(ValueError):
            validate_money_amount("-10")

    def test_exact_min(self):
        result = validate_money_amount("0.01", min_amount=Decimal("0.01"))
        assert result == Decimal("0.01")

    def test_exact_max(self):
        result = validate_money_amount("1000000", max_amount=Decimal("1000000"))
        assert result == Decimal("1000000.00")


class TestSanitizeHtml:

    def test_escapes_angle_brackets(self):
        result = sanitize_html("<script>alert('xss')</script>")
        assert "<script>" not in result
        assert "&lt;" in result

    def test_escapes_ampersand(self):
        result = sanitize_html("a & b")
        assert "&amp;" in result

    def test_escapes_quotes(self):
        result = sanitize_html('he said "hello"')
        assert "&quot;" in result

    def test_preserves_safe_bold(self):
        result = sanitize_html("<b>bold</b>")
        assert "<b>" in result
        assert "</b>" in result

    def test_preserves_safe_italic(self):
        result = sanitize_html("<i>italic</i>")
        assert "<i>" in result
        assert "</i>" in result

    def test_preserves_safe_code(self):
        result = sanitize_html("<code>code</code>")
        assert "<code>" in result
        assert "</code>" in result

    def test_plain_text_unchanged(self):
        assert sanitize_html("hello world") == "hello world"


class TestPaymentRequest:

    def test_valid_request(self):
        req = PaymentRequest(amount=Decimal("100"), currency="RUB", provider="cryptopay")
        assert req.amount == Decimal("100")

    def test_invalid_provider(self):
        with pytest.raises(ValidationError):
            PaymentRequest(amount=Decimal("100"), currency="RUB", provider="paypal")

    def test_zero_amount(self):
        with pytest.raises(ValidationError):
            PaymentRequest(amount=Decimal("0"), currency="RUB", provider="stars")

    def test_negative_amount(self):
        with pytest.raises(ValidationError):
            PaymentRequest(amount=Decimal("-10"), currency="RUB", provider="telegram")

    def test_too_many_decimals(self):
        with pytest.raises(ValidationError):
            PaymentRequest(amount=Decimal("10.123"), currency="RUB", provider="fiat")

    def test_invalid_currency_length(self):
        with pytest.raises(ValidationError):
            PaymentRequest(amount=Decimal("100"), currency="LONG", provider="stars")


class TestItemPurchaseRequest:

    def test_valid_request(self):
        req = ItemPurchaseRequest(item_name="Widget", user_id=12345)
        assert req.item_name == "Widget"

    def test_sql_patterns_allowed(self):
        req = ItemPurchaseRequest(item_name="Select Edition", user_id=1)
        assert req.item_name == "Select Edition"

    def test_control_characters_rejected(self):
        with pytest.raises(ValidationError):
            ItemPurchaseRequest(item_name="item\x00name", user_id=1)
        with pytest.raises(ValidationError):
            ItemPurchaseRequest(item_name="item\x1fname", user_id=1)

    def test_empty_name_rejected(self):
        with pytest.raises(ValidationError):
            ItemPurchaseRequest(item_name="", user_id=1)

    def test_invalid_user_id(self):
        with pytest.raises(ValidationError):
            ItemPurchaseRequest(item_name="Widget", user_id=0)


class TestCategoryRequest:

    def test_valid_category(self):
        req = CategoryRequest(name="Electronics")
        assert req.name == "Electronics"

    def test_sanitize_removes_html(self):
        req = CategoryRequest(name="<b>Bold</b> Category")
        assert req.sanitize_name() == "Bold Category"

    def test_sanitize_collapses_spaces(self):
        req = CategoryRequest(name="too   many   spaces")
        assert req.sanitize_name() == "too many spaces"

    def test_empty_name_rejected(self):
        with pytest.raises(ValidationError):
            CategoryRequest(name="")


class TestBroadcastMessage:

    def test_valid_html_message(self):
        msg = BroadcastMessage(text="<b>Hello</b> world")
        assert msg.text == "<b>Hello</b> world"

    def test_unbalanced_bold_tag(self):
        with pytest.raises(ValidationError):
            BroadcastMessage(text="<b>Hello world")

    def test_unbalanced_italic_tag(self):
        with pytest.raises(ValidationError):
            BroadcastMessage(text="<i>Hello</i><i>unclosed")

    def test_plain_text_valid(self):
        msg = BroadcastMessage(text="Hello world", parse_mode="HTML")
        assert msg.text == "Hello world"

    def test_too_long_rejected(self):
        with pytest.raises(ValidationError):
            BroadcastMessage(text="x" * 4097)

    def test_empty_rejected(self):
        with pytest.raises(ValidationError):
            BroadcastMessage(text="")
