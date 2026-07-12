from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select

from bot.database.main import Database
from bot.database.models.main import PromoCodes, PromoCodeUsages, Goods
from bot.database.methods.transactions import (
    buy_item_transaction, checkout_cart_transaction, redeem_balance_promo,
)
from bot.database.methods.read import validate_promo_for_item
from bot.database.methods.create import add_to_cart


def _future(hours: int = 1) -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=hours)


def _past(hours: int = 1) -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=hours)


async def _make_promo(code, discount_type="percent", value="10", *, active=True,
                      expires_at=None, max_uses=0, current_uses=0,
                      category_id=None, item_id=None):
    async with Database().session() as s:
        s.add(PromoCodes(
            code=code.upper(), discount_type=discount_type,
            discount_value=Decimal(str(value)), max_uses=max_uses,
            current_uses=current_uses, is_active=active, expires_at=expires_at,
            category_id=category_id, item_id=item_id,
        ))


async def _mark_used(code, user_id):
    async with Database().session() as s:
        pid = (await s.execute(
            select(PromoCodes.id).where(PromoCodes.code == code.upper())
        )).scalar()
        s.add(PromoCodeUsages(promo_id=pid, user_id=user_id))


async def _goods(name):
    async with Database().session() as s:
        return (await s.execute(select(Goods).where(Goods.name == name))).scalars().one()


# --- buy_item_transaction ---

class TestBuyPromoValidation:
    async def test_percent_promo_applied(self, user_factory, item_factory):
        await user_factory(telegram_id=800001, balance=1000)
        await item_factory(name="P1", price=100, values=[("v", False)])
        await _make_promo("PCT", "percent", "25")
        ok, msg, data = await buy_item_transaction(800001, "P1", promo_code="PCT")
        assert ok, msg
        assert data["price"] == 75.0

    async def test_fixed_promo_applied(self, user_factory, item_factory):
        await user_factory(telegram_id=800002, balance=1000)
        await item_factory(name="P2", price=100, values=[("v", False)])
        await _make_promo("FIX", "fixed", "30")
        ok, msg, data = await buy_item_transaction(800002, "P2", promo_code="FIX")
        assert ok, msg
        assert data["price"] == 70.0

    async def test_nonexistent_promo_invalid(self, user_factory, item_factory):
        await user_factory(telegram_id=800003, balance=1000)
        await item_factory(name="P3", price=100, values=[("v", False)])
        ok, msg, _ = await buy_item_transaction(800003, "P3", promo_code="NOPE")
        assert (ok, msg) == (False, "promo_invalid")

    async def test_inactive_promo_invalid(self, user_factory, item_factory):
        await user_factory(telegram_id=800004, balance=1000)
        await item_factory(name="P4", price=100, values=[("v", False)])
        await _make_promo("INACT", "percent", "10", active=False)
        ok, msg, _ = await buy_item_transaction(800004, "P4", promo_code="INACT")
        assert (ok, msg) == (False, "promo_invalid")

    async def test_balance_type_promo_invalid(self, user_factory, item_factory):
        await user_factory(telegram_id=800005, balance=1000)
        await item_factory(name="P5", price=100, values=[("v", False)])
        await _make_promo("BAL", "balance", "10")
        ok, msg, _ = await buy_item_transaction(800005, "P5", promo_code="BAL")
        assert (ok, msg) == (False, "promo_invalid")

    async def test_expired_promo(self, user_factory, item_factory):
        await user_factory(telegram_id=800006, balance=1000)
        await item_factory(name="P6", price=100, values=[("v", False)])
        await _make_promo("EXP", "percent", "10", expires_at=_past())
        ok, msg, _ = await buy_item_transaction(800006, "P6", promo_code="EXP")
        assert (ok, msg) == (False, "promo_expired")

    async def test_max_uses_reached(self, user_factory, item_factory):
        await user_factory(telegram_id=800007, balance=1000)
        await item_factory(name="P7", price=100, values=[("v", False)])
        await _make_promo("MAX", "percent", "10", max_uses=1, current_uses=1)
        ok, msg, _ = await buy_item_transaction(800007, "P7", promo_code="MAX")
        assert (ok, msg) == (False, "promo_max_uses")

    async def test_already_used(self, user_factory, item_factory):
        await user_factory(telegram_id=800008, balance=1000)
        await item_factory(name="P8", price=100, values=[("v", False)])
        await _make_promo("USED", "percent", "10")
        await _mark_used("USED", 800008)
        ok, msg, _ = await buy_item_transaction(800008, "P8", promo_code="USED")
        assert (ok, msg) == (False, "promo_already_used")

    async def test_wrong_item(self, user_factory, item_factory):
        await user_factory(telegram_id=800009, balance=1000)
        await item_factory(name="P9", price=100, values=[("v", False)])
        await item_factory(name="Other9", price=100, category="OtherCat9", values=[("v", False)])
        other = await _goods("Other9")
        await _make_promo("WITEM", "percent", "10", item_id=other.id)
        ok, msg, _ = await buy_item_transaction(800009, "P9", promo_code="WITEM")
        assert (ok, msg) == (False, "promo_wrong_item")

    async def test_wrong_category(self, user_factory, item_factory):
        await user_factory(telegram_id=800010, balance=1000)
        await item_factory(name="P10", price=100, category="Cat10", values=[("v", False)])
        await item_factory(name="Other10", price=100, category="OtherCat10", values=[("v", False)])
        other = await _goods("Other10")
        await _make_promo("WCAT", "percent", "10", category_id=other.category_id)
        ok, msg, _ = await buy_item_transaction(800010, "P10", promo_code="WCAT")
        assert (ok, msg) == (False, "promo_wrong_category")


# --- checkout_cart_transaction ---

class TestCartPromoValidation:
    async def test_cart_promo_applied(self, user_factory, item_factory):
        await user_factory(telegram_id=810001, balance=1000)
        await item_factory(name="C1", price=100, values=[("v", False)])
        await _make_promo("CART10", "percent", "10")
        await add_to_cart(810001, "C1", promo_code="CART10")
        ok, msg, results = await checkout_cart_transaction(810001)
        assert ok, msg
        assert results[0]["price"] == 90.0

    async def test_cart_promo_invalid_aborts(self, user_factory, item_factory):
        await user_factory(telegram_id=810002, balance=1000)
        await item_factory(name="C2", price=100, values=[("v", False)])
        await _make_promo("CEXP", "percent", "10", expires_at=_past())
        await add_to_cart(810002, "C2", promo_code="CEXP")
        ok, msg, _ = await checkout_cart_transaction(810002)
        assert (ok, msg) == (False, "promo_expired_during_checkout")


# --- validate_promo_for_item (read-only, granular keys) ---

class TestValidatePromoForItem:
    async def test_valid(self, item_factory):
        await item_factory(name="V1", price=100, values=[("v", False)])
        await _make_promo("VOK", "percent", "10")
        valid, key, data = await validate_promo_for_item("VOK", "V1", 820001)
        assert valid is True
        assert key == ""
        assert data["code"] == "VOK"

    async def test_not_found(self, item_factory):
        await item_factory(name="V2", price=100, values=[("v", False)])
        valid, key, _ = await validate_promo_for_item("MISSING", "V2", 820002)
        assert (valid, key) == (False, "promo.not_found")

    async def test_inactive(self, item_factory):
        await item_factory(name="V3", price=100, values=[("v", False)])
        await _make_promo("VINACT", "percent", "10", active=False)
        valid, key, _ = await validate_promo_for_item("VINACT", "V3", 820003)
        assert (valid, key) == (False, "promo.inactive")

    async def test_balance_type_rejected(self, item_factory):
        await item_factory(name="V4", price=100, values=[("v", False)])
        await _make_promo("VBAL", "balance", "10")
        valid, key, _ = await validate_promo_for_item("VBAL", "V4", 820004)
        assert (valid, key) == (False, "promo.not_balance_type")

    async def test_expired(self, item_factory):
        await item_factory(name="V5", price=100, values=[("v", False)])
        await _make_promo("VEXP", "percent", "10", expires_at=_past())
        valid, key, _ = await validate_promo_for_item("VEXP", "V5", 820005)
        assert (valid, key) == (False, "promo.expired")

    async def test_max_uses(self, item_factory):
        await item_factory(name="V6", price=100, values=[("v", False)])
        await _make_promo("VMAX", "percent", "10", max_uses=1, current_uses=1)
        valid, key, _ = await validate_promo_for_item("VMAX", "V6", 820006)
        assert (valid, key) == (False, "promo.max_uses_reached")

    async def test_already_used(self, item_factory):
        await item_factory(name="V7", price=100, values=[("v", False)])
        await _make_promo("VUSED", "percent", "10")
        await _mark_used("VUSED", 820007)
        valid, key, _ = await validate_promo_for_item("VUSED", "V7", 820007)
        assert (valid, key) == (False, "promo.already_used")

    async def test_wrong_item(self, item_factory):
        await item_factory(name="V8", price=100, values=[("v", False)])
        await item_factory(name="OtherV8", price=100, category="OCV8", values=[("v", False)])
        other = await _goods("OtherV8")
        await _make_promo("VWITEM", "percent", "10", item_id=other.id)
        valid, key, _ = await validate_promo_for_item("VWITEM", "V8", 820008)
        assert (valid, key) == (False, "promo.wrong_item")

    async def test_wrong_category(self, item_factory):
        await item_factory(name="V9", price=100, category="CV9", values=[("v", False)])
        await item_factory(name="OtherV9", price=100, category="OCV9", values=[("v", False)])
        other = await _goods("OtherV9")
        await _make_promo("VWCAT", "percent", "10", category_id=other.category_id)
        valid, key, _ = await validate_promo_for_item("VWCAT", "V9", 820009)
        assert (valid, key) == (False, "promo.wrong_category")


# --- redeem_balance_promo (balance type) ---

class TestRedeemBalancePromo:
    async def test_success(self, user_factory):
        await user_factory(telegram_id=830001, balance=0)
        await _make_promo("RBAL", "balance", "50")
        ok, key, amount = await redeem_balance_promo("RBAL", 830001)
        assert ok, key
        assert amount == Decimal("50")

    async def test_not_found(self, user_factory):
        await user_factory(telegram_id=830002, balance=0)
        ok, key, _ = await redeem_balance_promo("RMISS", 830002)
        assert (ok, key) == (False, "promo.not_found")

    async def test_inactive(self, user_factory):
        await user_factory(telegram_id=830003, balance=0)
        await _make_promo("RINACT", "balance", "50", active=False)
        ok, key, _ = await redeem_balance_promo("RINACT", 830003)
        assert (ok, key) == (False, "promo.inactive")

    async def test_not_balance_type(self, user_factory):
        await user_factory(telegram_id=830004, balance=0)
        await _make_promo("RPCT", "percent", "50")
        ok, key, _ = await redeem_balance_promo("RPCT", 830004)
        assert (ok, key) == (False, "promo.not_balance_type")

    async def test_expired(self, user_factory):
        await user_factory(telegram_id=830005, balance=0)
        await _make_promo("REXP", "balance", "50", expires_at=_past())
        ok, key, _ = await redeem_balance_promo("REXP", 830005)
        assert (ok, key) == (False, "promo.expired")

    async def test_max_uses(self, user_factory):
        await user_factory(telegram_id=830006, balance=0)
        await _make_promo("RMAX", "balance", "50", max_uses=1, current_uses=1)
        ok, key, _ = await redeem_balance_promo("RMAX", 830006)
        assert (ok, key) == (False, "promo.max_uses_reached")

    async def test_already_used(self, user_factory):
        await user_factory(telegram_id=830007, balance=0)
        await _make_promo("RUSED", "balance", "50")
        await _mark_used("RUSED", 830007)
        ok, key, _ = await redeem_balance_promo("RUSED", 830007)
        assert (ok, key) == (False, "promo.already_used")
