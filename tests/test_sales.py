from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from bot.database.main import Database
from bot.database.models.main import Goods, PromoCodes
from bot.database.methods.pricing import effective_price
from bot.database.methods.transactions import buy_item_transaction
from bot.database.methods.update import set_item_sale
from bot.database.methods.read import get_item_info
from bot.handlers.admin.sale_management import sale_item_name, sale_percent, sale_days
from bot.states import SaleFSM


def _future(hours: int = 1) -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=hours)


def _past(hours: int = 1) -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=hours)


async def _set_sale(item_name: str, percent, until) -> None:
    async with Database().session() as s:
        g = (await s.execute(select(Goods).where(Goods.name == item_name))).scalars().one()
        g.sale_percent = percent
        g.sale_until = until


async def _create_promo(code: str, discount_type: str, value, **kw) -> None:
    async with Database().session() as s:
        s.add(PromoCodes(
            code=code.upper(), discount_type=discount_type, discount_value=value,
            max_uses=0, current_uses=0, is_active=True, **kw,
        ))


# --- effective_price unit tests (no DB) ---

class TestEffectivePrice:

    @pytest.mark.parametrize("price,percent,until,expected_final,expected_on_sale", [
        # No sale configured at all.
        ("100.00", None, None, "100.00", False),
        ("100.00", Decimal("20"), _future(), "80.00", True),
        ("100.00", Decimal("20"), _past(), "100.00", False),        # expired
        ("100.00", Decimal("0"), _future(), "100.00", False),       # 0% is not a sale
        ("100.00", Decimal("150"), _future(), "0.00", True),        # clamped at 100%
        # A naive datetime is read as UTC rather than rejected.
        ("50.00", Decimal("10"), datetime.now() + timedelta(hours=1), "45.00", True),
        # Redis round-trips datetimes as strings (default=str), in two shapes.
        ("100.00", "20", _future().isoformat(), "80.00", True),     # ISO 'T' separator
        ("100.00", "20", str(_future()), "80.00", True),            # space separator
        ("100.00", "20", "not-a-date", "100.00", False),            # unparseable
    ])
    def test_pricing(self, price, percent, until, expected_final, expected_on_sale):
        final, on_sale, original = effective_price(
            {"price": Decimal(price), "sale_percent": percent, "sale_until": until}
        )
        assert final == Decimal(expected_final)
        assert on_sale is expected_on_sale
        assert original == Decimal(price)


# --- Purchase flow integration tests ---

class TestSalePurchase:

    async def test_purchase_charges_sale_price(self, user_factory, item_factory):
        await user_factory(telegram_id=500001, balance=1000)
        await item_factory(name="SaleItem", price=100, values=[("code-1", False)])
        await _set_sale("SaleItem", Decimal("20"), _future())

        success, msg, data = await buy_item_transaction(500001, "SaleItem")
        assert success is True, msg
        assert data["price"] == 80.0
        assert data["new_balance"] == 920.0

    async def test_expired_sale_charges_full_price(self, user_factory, item_factory):
        await user_factory(telegram_id=500002, balance=1000)
        await item_factory(name="OldSale", price=100, values=[("code-2", False)])
        await _set_sale("OldSale", Decimal("20"), _past())

        success, msg, data = await buy_item_transaction(500002, "OldSale")
        assert success is True, msg
        assert data["price"] == 100.0

    async def test_sale_and_promo_stack(self, user_factory, item_factory):
        await user_factory(telegram_id=500003, balance=1000)
        await item_factory(name="StackItem", price=100, values=[("code-3", False)])
        await _set_sale("StackItem", Decimal("20"), _future())  # -> 80
        await _create_promo("SAVE10", "percent", Decimal("10"))  # 10% off the 80

        success, msg, data = await buy_item_transaction(500003, "StackItem", promo_code="SAVE10")
        assert success is True, msg
        assert data["price"] == 72.0  # 100 * 0.8 * 0.9
        assert data["discount"]["original_price"] == 80.0  # promo discounts off sale price


# --- set_item_sale DB method ---

class TestSetItemSale:

    async def test_sets_sale_fields(self, item_factory):
        await item_factory(name="M1", price=100, values=[("v", False)])

        ok = await set_item_sale("M1", Decimal("25"), _future())
        assert ok is True

        info = await get_item_info("M1")
        final, on_sale, _ = effective_price(info)
        assert on_sale is True
        assert final == Decimal("75.00")

    async def test_clears_sale(self, item_factory):
        await item_factory(name="M2", price=100, values=[("v", False)])
        await _set_sale("M2", Decimal("30"), _future())

        ok = await set_item_sale("M2", None, None)
        assert ok is True

        info = await get_item_info("M2")
        _, on_sale, _ = effective_price(info)
        assert on_sale is False

    async def test_missing_item_returns_false(self):
        assert await set_item_sale("NoSuchItem", Decimal("10"), _future()) is False


# --- Admin FSM flow ---

class TestSaleAdminFlow:

    async def test_fsm_sets_sale(self, item_factory, make_message, fsm_context):
        await item_factory(name="FsmSale", price=100, values=[("v", False)])

        await sale_item_name(make_message(text="FsmSale", user_id=1), fsm_context)
        await sale_percent(make_message(text="25", user_id=1), fsm_context)
        await sale_days(make_message(text="5", user_id=1), fsm_context)

        info = await get_item_info("FsmSale")
        final, on_sale, _ = effective_price(info)
        assert on_sale is True
        assert final == Decimal("75.00")

    async def test_fsm_zero_percent_disables(self, item_factory, make_message, fsm_context):
        await item_factory(name="FsmOff", price=100, values=[("v", False)])
        await _set_sale("FsmOff", Decimal("40"), _future())

        await sale_item_name(make_message(text="FsmOff", user_id=1), fsm_context)
        await sale_percent(make_message(text="0", user_id=1), fsm_context)

        info = await get_item_info("FsmOff")
        _, on_sale, _ = effective_price(info)
        assert on_sale is False

    async def test_fsm_invalid_percent_rejected(self, item_factory, make_message, fsm_context):
        await item_factory(name="FsmBad", price=100, values=[("v", False)])

        await sale_item_name(make_message(text="FsmBad", user_id=1), fsm_context)
        msg = make_message(text="150", user_id=1)
        await sale_percent(msg, fsm_context)
        # Rejected: state stays on percent, no days prompt advanced
        assert await fsm_context.get_state() == SaleFSM.waiting_percent
