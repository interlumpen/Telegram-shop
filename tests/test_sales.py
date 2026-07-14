from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from bot.database.main import Database
from bot.database.models.main import Goods, PromoCodes
from bot.database.methods.pricing import effective_price
from bot.database.methods.transactions import buy_item_transaction
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

    def test_no_sale_returns_original(self):
        final, on_sale, original = effective_price(
            {"price": Decimal("100.00"), "sale_percent": None, "sale_until": None}
        )
        assert final == Decimal("100.00")
        assert on_sale is False
        assert original == Decimal("100.00")

    def test_active_sale_applies_discount(self):
        final, on_sale, original = effective_price(
            {"price": Decimal("100.00"), "sale_percent": Decimal("20"), "sale_until": _future()}
        )
        assert final == Decimal("80.00")
        assert on_sale is True
        assert original == Decimal("100.00")

    def test_expired_sale_falls_back_to_original(self):
        final, on_sale, _ = effective_price(
            {"price": Decimal("100.00"), "sale_percent": Decimal("20"), "sale_until": _past()}
        )
        assert final == Decimal("100.00")
        assert on_sale is False

    def test_zero_percent_is_not_a_sale(self):
        final, on_sale, _ = effective_price(
            {"price": Decimal("100.00"), "sale_percent": Decimal("0"), "sale_until": _future()}
        )
        assert final == Decimal("100.00")
        assert on_sale is False

    def test_percent_clamped_to_100(self):
        final, on_sale, _ = effective_price(
            {"price": Decimal("100.00"), "sale_percent": Decimal("150"), "sale_until": _future()}
        )
        assert final == Decimal("0.00")
        assert on_sale is True

    def test_naive_sale_until_treated_as_utc(self):
        naive_future = datetime.now() + timedelta(hours=1)
        final, on_sale, _ = effective_price(
            {"price": Decimal("50.00"), "sale_percent": Decimal("10"), "sale_until": naive_future}
        )
        assert on_sale is True
        assert final == Decimal("45.00")

    def test_string_sale_until_from_cache(self):
        # Redis round-trip serializes datetime -> ISO string (default=str).
        iso = _future().isoformat()
        final, on_sale, _ = effective_price(
            {"price": Decimal("100.00"), "sale_percent": "20", "sale_until": iso}
        )
        assert on_sale is True
        assert final == Decimal("80.00")

    def test_string_sale_until_space_separator(self):
        # str(datetime) uses a space separator instead of 'T'.
        s = str(_future())
        final, on_sale, _ = effective_price(
            {"price": Decimal("100.00"), "sale_percent": "20", "sale_until": s}
        )
        assert on_sale is True
        assert final == Decimal("80.00")

    def test_malformed_sale_until_falls_back(self):
        final, on_sale, _ = effective_price(
            {"price": Decimal("100.00"), "sale_percent": "20", "sale_until": "not-a-date"}
        )
        assert on_sale is False
        assert final == Decimal("100.00")


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
        from bot.database.methods.update import set_item_sale
        from bot.database.methods.read import get_item_info
        await item_factory(name="M1", price=100, values=[("v", False)])

        ok = await set_item_sale("M1", Decimal("25"), _future())
        assert ok is True

        info = await get_item_info("M1")
        final, on_sale, _ = effective_price(info)
        assert on_sale is True
        assert final == Decimal("75.00")

    async def test_clears_sale(self, item_factory):
        from bot.database.methods.update import set_item_sale
        from bot.database.methods.read import get_item_info
        await item_factory(name="M2", price=100, values=[("v", False)])
        await _set_sale("M2", Decimal("30"), _future())

        ok = await set_item_sale("M2", None, None)
        assert ok is True

        info = await get_item_info("M2")
        _, on_sale, _ = effective_price(info)
        assert on_sale is False

    async def test_missing_item_returns_false(self):
        from bot.database.methods.update import set_item_sale
        assert await set_item_sale("NoSuchItem", Decimal("10"), _future()) is False


# --- Admin FSM flow ---

class TestSaleAdminFlow:

    async def test_fsm_sets_sale(self, item_factory, make_message, fsm_context):
        from bot.database.methods.read import get_item_info
        from bot.handlers.admin.sale_management import sale_item_name, sale_percent, sale_days
        await item_factory(name="FsmSale", price=100, values=[("v", False)])

        await sale_item_name(make_message(text="FsmSale", user_id=1), fsm_context)
        await sale_percent(make_message(text="25", user_id=1), fsm_context)
        await sale_days(make_message(text="5", user_id=1), fsm_context)

        info = await get_item_info("FsmSale")
        final, on_sale, _ = effective_price(info)
        assert on_sale is True
        assert final == Decimal("75.00")

    async def test_fsm_zero_percent_disables(self, item_factory, make_message, fsm_context):
        from bot.database.methods.read import get_item_info
        from bot.handlers.admin.sale_management import sale_item_name, sale_percent
        await item_factory(name="FsmOff", price=100, values=[("v", False)])
        await _set_sale("FsmOff", Decimal("40"), _future())

        await sale_item_name(make_message(text="FsmOff", user_id=1), fsm_context)
        await sale_percent(make_message(text="0", user_id=1), fsm_context)

        info = await get_item_info("FsmOff")
        _, on_sale, _ = effective_price(info)
        assert on_sale is False

    async def test_fsm_invalid_percent_rejected(self, item_factory, make_message, fsm_context):
        from bot.handlers.admin.sale_management import sale_item_name, sale_percent
        await item_factory(name="FsmBad", price=100, values=[("v", False)])

        await sale_item_name(make_message(text="FsmBad", user_id=1), fsm_context)
        msg = make_message(text="150", user_id=1)
        await sale_percent(msg, fsm_context)
        # Rejected: state stays on percent, no days prompt advanced
        assert await fsm_context.get_state() == SaleFSM.waiting_percent
