from datetime import datetime, timezone
from decimal import Decimal
from typing import Any


def _get(goods: Any, key: str):
    """Read a field from either an ORM object or a plain dict."""
    if isinstance(goods, dict):
        return goods.get(key)
    return getattr(goods, key, None)


def coerce_sale_until(value: Any) -> datetime | None:
    """Normalize a sale_until value to a timezone-aware datetime (or None).

    Product dicts read from the Redis cache are JSON-serialized (datetime ->
    ISO string via default=str), so this accepts either a datetime or a string.
    Naive datetimes are treated as UTC.
    """
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value


def effective_price(goods: Any, now: datetime | None = None) -> tuple[Decimal, bool, Decimal]:
    """Return (final_price, on_sale, original_price) for a product.

    'goods' may be an ORM 'Goods' instance or a dict with 'price',
    'sale_percent' and 'sale_until' keys. The sale applies only while
    'sale_until' is in the future and 'sale_percent' is a positive percent
    """
    original = Decimal(str(_get(goods, 'price'))).quantize(Decimal("0.01"))

    sale_percent = _get(goods, 'sale_percent')
    sale_until = coerce_sale_until(_get(goods, 'sale_until'))

    if sale_percent is None or sale_until is None:
        return original, False, original

    now = now or datetime.now(timezone.utc)

    pct = Decimal(str(sale_percent))
    if sale_until <= now or pct <= 0:
        return original, False, original

    pct = min(pct, Decimal(100))
    final = (original * (1 - pct / 100)).quantize(Decimal("0.01"))
    if final < 0:
        final = Decimal("0.00")
    return final, True, original
