from decimal import Decimal

from bot.database.main import Database
import pytest

from bot.database.methods.transactions import _buy_item_transaction as buy_item_transaction, \
    _process_payment_with_referral as process_payment_with_referral, \
    _admin_balance_change as admin_balance_change
from bot.database.methods.create import _create_pending_payment as create_pending_payment
from bot.database.models.main import BoughtGoods, ItemValues, Goods, Payments, Operations, ReferralEarnings, User


def _get_balance(telegram_id: int) -> float:
    """Read user balance directly from DB to avoid cache issues."""
    with Database().session() as s:
        user = s.query(User).filter(User.telegram_id == telegram_id).one()
        return float(user.balance)


class TestBuyItemTransaction:

    def test_buy_item_success(self, user_factory, item_factory):
        user_factory(telegram_id=100001, balance=500)
        item_factory(name="Widget", price=100, values=[("val1", False)])

        success, msg, data = buy_item_transaction(100001, "Widget")

        assert success is True
        assert msg == "success"
        assert data is not None
        assert data["item_name"] == "Widget"
        assert data["value"] == "val1"
        assert data["price"] == 100.0
        assert data["new_balance"] == 400.0

        # Verify DB state
        assert _get_balance(100001) == 400.0

        with Database().session() as s:
            bought = s.query(BoughtGoods).filter(
                BoughtGoods.buyer_id == 100001
            ).all()
            assert len(bought) == 1
            assert bought[0].item_name == "Widget"
            assert bought[0].value == "val1"
            assert float(bought[0].price) == 100.0

            widget = s.query(Goods).filter(Goods.name == "Widget").first()
            iv_count = s.query(ItemValues).filter(
                ItemValues.item_id == widget.id
            ).count()
            assert iv_count == 0

    def test_buy_item_insufficient_funds(self, user_factory, item_factory):
        user_factory(telegram_id=100002, balance=50)
        item_factory(name="Expensive", price=100, values=[("val1", False)])

        success, msg, data = buy_item_transaction(100002, "Expensive")

        assert success is False
        assert msg == "insufficient_funds"
        assert data is None

        # Balance unchanged
        assert _get_balance(100002) == 50.0

    def test_buy_item_out_of_stock(self, user_factory, item_factory):
        user_factory(telegram_id=100003, balance=500)
        # Item exists but no values
        item_factory(name="Empty", price=100, values=None)

        success, msg, data = buy_item_transaction(100003, "Empty")

        assert success is False
        assert msg == "out_of_stock"
        assert data is None

    def test_buy_item_user_not_found(self, item_factory):
        item_factory(name="Gadget", price=100, values=[("val1", False)])

        success, msg, data = buy_item_transaction(999999, "Gadget")

        assert success is False
        assert msg == "user_not_found"
        assert data is None

    def test_buy_item_item_not_found(self, user_factory):
        user_factory(telegram_id=100004, balance=500)

        success, msg, data = buy_item_transaction(100004, "NonExistent")

        assert success is False
        assert msg == "item_not_found"
        assert data is None

    def test_buy_item_infinite_stock(self, user_factory, item_factory):
        user_factory(telegram_id=100005, balance=500)
        item_factory(name="InfItem", price=100, values=[("infinite_val", True)])

        success, msg, data = buy_item_transaction(100005, "InfItem")

        assert success is True
        assert msg == "success"
        assert data["value"] == "infinite_val"
        assert data["new_balance"] == 400.0

        assert _get_balance(100005) == 400.0

        # ItemValues should still exist
        with Database().session() as s:
            inf_item = s.query(Goods).filter(Goods.name == "InfItem").first()
            iv_count = s.query(ItemValues).filter(
                ItemValues.item_id == inf_item.id
            ).count()
            assert iv_count == 1

    def test_buy_item_multiple_purchases(self, user_factory, item_factory):
        user_factory(telegram_id=100006, balance=1000)
        item_factory(
            name="Multi",
            price=100,
            values=[("v1", False), ("v2", False), ("v3", False)],
        )

        purchased_values = []
        for _ in range(3):
            success, msg, data = buy_item_transaction(100006, "Multi")
            assert success is True
            assert msg == "success"
            purchased_values.append(data["value"])

        # All three values should have been purchased
        assert sorted(purchased_values) == ["v1", "v2", "v3"]

        # Fourth attempt should be out of stock
        success, msg, data = buy_item_transaction(100006, "Multi")
        assert success is False
        assert msg == "out_of_stock"

        # Verify balance: 1000 - 3*100 = 700
        assert _get_balance(100006) == 700.0

        # All ItemValues gone
        with Database().session() as s:
            multi = s.query(Goods).filter(Goods.name == "Multi").first()
            iv_count = s.query(ItemValues).filter(
                ItemValues.item_id == multi.id
            ).count()
            assert iv_count == 0

    def test_buy_item_exact_balance(self, user_factory, item_factory):
        user_factory(telegram_id=100007, balance=100)
        item_factory(name="Exact", price=100, values=[("exactval", False)])

        success, msg, data = buy_item_transaction(100007, "Exact")

        assert success is True
        assert msg == "success"
        assert data["new_balance"] == 0.0

        assert _get_balance(100007) == 0.0


class TestProcessPaymentWithReferral:

    def test_payment_success(self, user_factory):
        user_factory(telegram_id=200001, balance=0)

        success, msg = process_payment_with_referral(
            user_id=200001,
            amount=Decimal("500"),
            provider="test_provider",
            external_id="ext_001",
        )

        assert success is True
        assert msg == "success"

        # Balance increased
        assert _get_balance(200001) == 500.0

        # Payment record created
        with Database().session() as s:
            payment = s.query(Payments).filter(
                Payments.external_id == "ext_001"
            ).first()
            assert payment is not None
            assert payment.status == "succeeded"
            assert float(payment.amount) == 500.0
            assert payment.provider == "test_provider"

            # Operation record created
            ops = s.query(Operations).filter(
                Operations.user_id == 200001
            ).all()
            assert len(ops) == 1
            assert float(ops[0].operation_value) == 500.0

    def test_payment_idempotency(self, user_factory):
        user_factory(telegram_id=200002, balance=0)

        # First call succeeds
        success1, msg1 = process_payment_with_referral(
            user_id=200002,
            amount=Decimal("300"),
            provider="prov_a",
            external_id="ext_dup",
        )
        assert success1 is True
        assert msg1 == "success"

        # Second call with same provider+external_id
        success2, msg2 = process_payment_with_referral(
            user_id=200002,
            amount=Decimal("300"),
            provider="prov_a",
            external_id="ext_dup",
        )
        assert success2 is False
        assert msg2 == "already_processed"

        # Balance only credited once
        assert _get_balance(200002) == 300.0

    def test_payment_with_referral_bonus(self, user_factory):
        # Create referrer first
        user_factory(telegram_id=200010, balance=0)
        # Create user with referrer
        user_factory(telegram_id=200003, balance=0, referral_id=200010)

        success, msg = process_payment_with_referral(
            user_id=200003,
            amount=Decimal("100"),
            provider="prov_ref",
            external_id="ext_ref_001",
            referral_percent=10,
        )

        assert success is True
        assert msg == "success"

        # User got 100
        assert _get_balance(200003) == 100.0

        # Referrer got 10 (10% of 100)
        assert _get_balance(200010) == 10.0

        # ReferralEarnings record created
        with Database().session() as s:
            earnings = s.query(ReferralEarnings).filter(
                ReferralEarnings.referrer_id == 200010,
                ReferralEarnings.referral_id == 200003,
            ).all()
            assert len(earnings) == 1
            assert float(earnings[0].amount) == 10.0
            assert float(earnings[0].original_amount) == 100.0

    def test_payment_no_referrer(self, user_factory):
        # User without referral_id
        user_factory(telegram_id=200004, balance=0)

        success, msg = process_payment_with_referral(
            user_id=200004,
            amount=Decimal("200"),
            provider="prov_noref",
            external_id="ext_noref",
            referral_percent=10,
        )

        assert success is True
        assert msg == "success"

        # No referral earnings created
        with Database().session() as s:
            earnings = s.query(ReferralEarnings).filter(
                ReferralEarnings.referral_id == 200004
            ).count()
            assert earnings == 0

    def test_payment_zero_percent(self, user_factory):
        # Create referrer
        user_factory(telegram_id=200020, balance=0)
        # Create user with referrer
        user_factory(telegram_id=200005, balance=0, referral_id=200020)

        success, msg = process_payment_with_referral(
            user_id=200005,
            amount=Decimal("100"),
            provider="prov_zero",
            external_id="ext_zero",
            referral_percent=0,
        )

        assert success is True
        assert msg == "success"

        # Referrer balance unchanged
        assert _get_balance(200020) == 0.0

        # No referral earnings
        with Database().session() as s:
            earnings = s.query(ReferralEarnings).filter(
                ReferralEarnings.referrer_id == 200020
            ).count()
            assert earnings == 0

    def test_payment_existing_pending(self, user_factory):
        user_factory(telegram_id=200006, balance=0)

        # Create a pending payment first
        create_pending_payment(
            provider="prov_pend",
            external_id="ext_pend",
            user_id=200006,
            amount=250,
            currency="RUB",
        )

        # Verify it exists as pending
        with Database().session() as s:
            p = s.query(Payments).filter(
                Payments.provider == "prov_pend",
                Payments.external_id == "ext_pend",
            ).first()
            assert p is not None
            assert p.status == "pending"

        # Now process it
        success, msg = process_payment_with_referral(
            user_id=200006,
            amount=Decimal("250"),
            provider="prov_pend",
            external_id="ext_pend",
        )

        assert success is True
        assert msg == "success"

        # Status updated to succeeded
        with Database().session() as s:
            p = s.query(Payments).filter(
                Payments.provider == "prov_pend",
                Payments.external_id == "ext_pend",
            ).first()
            assert p.status == "succeeded"

        # Balance credited
        assert _get_balance(200006) == 250.0

    def test_payment_large_amount(self, user_factory):
        user_factory(telegram_id=200007, balance=0)

        success, msg = process_payment_with_referral(
            user_id=200007,
            amount=Decimal("99999"),
            provider="prov_large",
            external_id="ext_large",
        )

        assert success is True
        assert msg == "success"

        assert _get_balance(200007) == 99999.0

        # Verify Decimal precision in payment record
        with Database().session() as s:
            payment = s.query(Payments).filter(
                Payments.external_id == "ext_large"
            ).first()
            assert payment is not None
            assert float(payment.amount) == 99999.0


class TestAdminBalanceChange:

    def test_topup_success(self, user_factory):
        user_factory(telegram_id=300001, balance=100)

        success, msg = admin_balance_change(300001, 500)

        assert success is True
        assert msg == "success"
        assert _get_balance(300001) == 600.0

        # Operation record created
        with Database().session() as s:
            ops = s.query(Operations).filter(
                Operations.user_id == 300001
            ).all()
            assert len(ops) == 1
            assert float(ops[0].operation_value) == 500.0

    def test_deduct_success(self, user_factory):
        user_factory(telegram_id=300002, balance=500)

        success, msg = admin_balance_change(300002, -200)

        assert success is True
        assert msg == "success"
        assert _get_balance(300002) == 300.0

        # Operation record created with negative value
        with Database().session() as s:
            ops = s.query(Operations).filter(
                Operations.user_id == 300002
            ).all()
            assert len(ops) == 1
            assert float(ops[0].operation_value) == -200.0

    def test_deduct_insufficient_funds(self, user_factory):
        user_factory(telegram_id=300003, balance=100)

        with pytest.raises(ValueError, match="insufficient_funds"):
            admin_balance_change(300003, -200)

        # Balance unchanged
        assert _get_balance(300003) == 100.0

        # No operation record created
        with Database().session() as s:
            ops = s.query(Operations).filter(
                Operations.user_id == 300003
            ).all()
            assert len(ops) == 0

    def test_deduct_exact_balance(self, user_factory):
        user_factory(telegram_id=300004, balance=500)

        success, msg = admin_balance_change(300004, -500)

        assert success is True
        assert _get_balance(300004) == 0.0

    def test_user_not_found(self):
        success, msg = admin_balance_change(999888, 100)

        assert success is False
        assert msg == "user_not_found"

    def test_topup_and_deduct_atomic(self, user_factory):
        """Verify that balance and operation are created atomically."""
        user_factory(telegram_id=300005, balance=1000)

        admin_balance_change(300005, 500)
        admin_balance_change(300005, -300)

        assert _get_balance(300005) == 1200.0

        with Database().session() as s:
            ops = s.query(Operations).filter(
                Operations.user_id == 300005
            ).order_by(Operations.id).all()
            assert len(ops) == 2
            assert float(ops[0].operation_value) == 500.0
            assert float(ops[1].operation_value) == -300.0
