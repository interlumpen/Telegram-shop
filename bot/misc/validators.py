from decimal import Decimal
from typing import Optional, Annotated, Self
from pydantic import BaseModel, Field, StringConstraints, field_validator, model_validator
import re


class PaymentRequest(BaseModel):
    """Validate payment request data"""
    amount: Decimal = Field(..., gt=0, le=100000)
    currency: str = Field(..., min_length=3, max_length=3)
    provider: str = Field(..., pattern="^(telegram|stars|cryptopay|fiat)$")

    @field_validator('amount')
    @classmethod
    def validate_amount(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError('Amount must be positive')
        # Prevent too precise amounts (max 2 decimal places)
        if v.as_tuple().exponent < -2:
            raise ValueError('Amount can have maximum 2 decimal places')
        return v


class ItemPurchaseRequest(BaseModel):
    """Validate item purchase request"""
    item_name: Annotated[str, StringConstraints(min_length=1, max_length=100, strip_whitespace=True)]
    user_id: int = Field(..., gt=0)

    @field_validator('item_name')
    @classmethod
    def validate_item_name(cls, v: str) -> str:
        # Prevent SQL injection patterns
        dangerous_patterns = [
            r"(--|#|\/\*|\*\/|;)",  # SQL comments and terminators
            r"(union|select|insert|update|delete|drop|create|alter|exec|execute)",  # SQL keywords
            r"(script|javascript|onclick|onerror|onload)",  # XSS patterns
        ]

        for pattern in dangerous_patterns:
            if re.search(pattern, v, re.IGNORECASE):
                raise ValueError(f'Invalid characters in item name')
        return v


class UserDataUpdate(BaseModel):
    """Validate user data updates"""
    telegram_id: int = Field(..., gt=0)
    balance: Optional[Decimal] = Field(None, ge=0, le=1000000)

    # Removed role_id as it's not used in the current implementation

    @field_validator('balance')
    @classmethod
    def validate_balance(cls, v: Optional[Decimal]) -> Optional[Decimal]:
        if v is not None and v < 0:
            raise ValueError('Balance cannot be negative')
        return v


class CategoryRequest(BaseModel):
    """Validate category operations"""
    name: Annotated[str, StringConstraints(min_length=1, max_length=100, strip_whitespace=True)]

    def sanitize_name(self) -> str:
        """Sanitize the category name"""
        # Remove any HTML/script tags
        v = re.sub(r'<[^>]*>', '', self.name)
        # Remove multiple spaces
        v = re.sub(r'\s+', ' ', v)
        return v.strip()


class BroadcastMessage(BaseModel):
    """Validate broadcast message"""
    text: Annotated[str, StringConstraints(min_length=1, max_length=4096)]
    parse_mode: Optional[str] = Field("HTML", pattern="^(HTML|Markdown|MarkdownV2)$")

    @model_validator(mode='after')
    def validate_html_tags(self) -> Self:
        """Validate HTML tags after all fields are set"""
        if self.parse_mode == 'HTML':
            # Basic HTML validation - check for balanced tags
            allowed_tags = ['b', 'i', 'u', 's', 'code', 'pre', 'a']

            # Simple check for unclosed tags
            for tag in allowed_tags:
                open_count = self.text.count(f'<{tag}>')
                # Also check for tags with attributes
                open_with_attrs = self.text.count(f'<{tag} ')
                total_open = open_count + open_with_attrs
                close_count = self.text.count(f'</{tag}>')

                if total_open != close_count:
                    raise ValueError(f'Unbalanced HTML tag: {tag}')
        return self


class SearchQuery(BaseModel):
    """Validate search queries"""
    query: Annotated[str, StringConstraints(min_length=1, max_length=255, strip_whitespace=True)]
    limit: int = Field(10, ge=1, le=100)

    # Removed offset as it's not used in the current implementation

    def sanitize_query(self, v: str) -> str:
        """Sanitize the search query"""
        # Remove special characters that could break search
        v = re.sub(r'[^\w\s\-.]', '', self.query)
        return v.strip()


# Helper functions for validation
def validate_telegram_id(telegram_id) -> int:
    """Validate and convert telegram ID"""
    try:
        tid = int(telegram_id)
        if tid <= 0:
            raise ValueError("Telegram ID must be positive")
        if tid > 9999999999:  # Max reasonable telegram ID
            raise ValueError("Invalid telegram ID")
        return tid
    except (ValueError, TypeError) as e:
        raise ValueError(f"Invalid telegram ID: {e}")


def validate_money_amount(amount, min_amount: Decimal = Decimal("0.01"),
                          max_amount: Decimal = Decimal("1000000")) -> Decimal:
    """Validate money amount"""
    try:
        decimal_amount = Decimal(str(amount))

        if decimal_amount < min_amount:
            raise ValueError(f"Amount must be at least {min_amount}")
        if decimal_amount > max_amount:
            raise ValueError(f"Amount cannot exceed {max_amount}")

        # Round to 2 decimal places
        return decimal_amount.quantize(Decimal("0.01"))
    except Exception as e:
        raise ValueError(f"Invalid amount: {e}")


def sanitize_html(text: str) -> str:
    """Sanitize HTML for safe display"""
    # Escape dangerous characters
    text = text.replace('&', '&amp;')
    text = text.replace('<', '&lt;')
    text = text.replace('>', '&gt;')
    text = text.replace('"', '&quot;')
    text = text.replace("'", '&#39;')

    # Allow only safe tags back
    safe_tags = {
        '&lt;b&gt;': '<b>', '&lt;/b&gt;': '</b>',
        '&lt;i&gt;': '<i>', '&lt;/i&gt;': '</i>',
        '&lt;u&gt;': '<u>', '&lt;/u&gt;': '</u>',
        '&lt;code&gt;': '<code>', '&lt;/code&gt;': '</code>',
    }

    for escaped, original in safe_tags.items():
        text = text.replace(escaped, original)

    return text
