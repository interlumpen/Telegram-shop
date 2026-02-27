import datetime
from decimal import Decimal

from bot.database.methods.create import create_user, create_item, add_values_to_item, create_operation, \
    create_pending_payment, create_referral_earning

from bot.database.methods.read import (
    check_user, check_role, get_role_id_by_name, check_role_name_by_id, select_max_role_id, select_today_users,
    get_user_count, get_all_users, check_category, get_item_info, get_item_info, check_value, select_item_values_amount,
    select_count_items, select_count_goods, select_count_categories, select_user_items, select_user_operations,
    check_user_referrals, get_user_referral, get_referral_earnings_stats, get_one_referral_earning,
    select_today_orders, select_all_orders, select_today_operations, select_all_operations, select_users_balance,
)
from bot.database.methods.update import update_balance, set_role, set_user_blocked, is_user_blocked, update_item, \
    update_category

from bot.database.methods.delete import delete_item, delete_only_items, delete_item_from_position, delete_category


NOW = datetime.datetime.now()
TODAY_STR = NOW.strftime("%Y-%m-%d")


class TestUserCRUD:
    def test_create_user_and_check(self, user_factory):
        user = user_factory(telegram_id=1001)
        assert user is not None
        assert user["telegram_id"] == 1001

    def test_create_user_duplicate_ignored(self, user_factory):
        user_factory(telegram_id=2001)
        # Creating again should not raise
        create_user(2001, NOW, referral_id=None, role=1)
        assert get_user_count() == 1

    def test_check_user_not_found(self):
        result = check_user(999999)
        assert result is None

    def test_get_user_count(self, user_factory):
        assert get_user_count() == 0
        user_factory(telegram_id=3001)
        user_factory(telegram_id=3002)
        assert get_user_count() == 2

    def test_get_all_users(self, user_factory):
        user_factory(telegram_id=4001)
        user_factory(telegram_id=4002)
        users = get_all_users()
        ids = [row[0] for row in users]
        assert 4001 in ids
        assert 4002 in ids

    def test_select_today_users(self, user_factory):
        user_factory(telegram_id=5001)
        count = select_today_users(TODAY_STR)
        assert count >= 1

    def test_select_today_users_wrong_date(self, user_factory):
        user_factory(telegram_id=5002)
        count = select_today_users("2000-01-01")
        assert count == 0

    def test_create_user_with_referral(self, user_factory):
        user_factory(telegram_id=6001)
        user_factory(telegram_id=6002, referral_id=6001)
        ref = get_user_referral(6002)
        assert ref == 6001


class TestRoleCRUD:
    def test_get_role_id_by_name_user(self):
        role_id = get_role_id_by_name("USER")
        assert role_id is not None

    def test_get_role_id_by_name_admin(self):
        role_id = get_role_id_by_name("ADMIN")
        assert role_id is not None

    def test_get_role_id_by_name_nonexistent(self):
        role_id = get_role_id_by_name("NONEXISTENT")
        assert role_id is None

    def test_check_role_name_by_id(self):
        role_id = get_role_id_by_name("USER")
        name = check_role_name_by_id(role_id)
        assert name == "USER"

    def test_select_max_role_id(self):
        max_id = select_max_role_id()
        assert max_id is not None
        assert max_id >= 1

    def test_check_role_returns_permissions(self, user_factory):
        user_factory(telegram_id=7001)
        perms = check_role(7001)
        # USER role has USE=1 permission
        assert perms & 1 == 1

    def test_check_role_nonexistent_user(self):
        perms = check_role(999888)
        assert perms == 0

    def test_set_role(self, user_factory):
        user_factory(telegram_id=7002)
        admin_role_id = get_role_id_by_name("ADMIN")
        set_role(7002, admin_role_id)
        perms = check_role(7002)
        # ADMIN has BROADCAST=2 permission
        assert perms & 2 == 2


class TestCategoryCRUD:
    def test_create_and_check_category(self, category_factory):
        category_factory("Electronics")
        cat = check_category("Electronics")
        assert cat is not None
        assert cat["name"] == "Electronics"

    def test_create_category_duplicate_ignored(self, category_factory):
        category_factory("Books")
        category_factory("Books")
        assert select_count_categories() == 1

    def test_check_category_not_found(self):
        assert check_category("Nonexistent") is None

    def test_select_count_categories(self, category_factory):
        category_factory("CatA")
        category_factory("CatB")
        assert select_count_categories() == 2

    def test_update_category_rename(self, category_factory):
        category_factory("OldCat")
        update_category("OldCat", "NewCat")
        assert check_category("OldCat") is None
        assert check_category("NewCat") is not None

    def test_delete_category(self, category_factory):
        category_factory("ToDelete")
        delete_category("ToDelete")
        assert check_category("ToDelete") is None


class TestItemCRUD:
    def test_create_and_get_item_info(self, item_factory):
        item_factory(name="Widget", price=50, category="Gadgets")
        item = get_item_info("Widget")
        assert item is not None
        assert item["name"] == "Widget"
        assert item["price"] == Decimal("50")

    def test_get_item_info(self, item_factory):
        item_factory(name="InfoItem", price=75, category="InfoCat", description="Desc here")
        info = get_item_info("InfoItem")
        assert info is not None
        assert info["description"] == "Desc here"

    def test_create_item_duplicate_ignored(self, item_factory):
        item_factory(name="DupItem", category="DupCat")
        create_item("DupItem", "desc2", 200, "DupCat")
        assert select_count_goods() == 1

    def test_add_values_to_item(self, item_factory):
        item_factory(name="ValItem", category="ValCat")
        result = add_values_to_item("ValItem", "code123", False)
        assert result is True
        assert select_item_values_amount("ValItem") == 1

    def test_add_values_duplicate_returns_false(self, item_factory):
        item_factory(name="DupVal", category="DupValCat")
        add_values_to_item("DupVal", "abc", False)
        result = add_values_to_item("DupVal", "abc", False)
        assert result is False

    def test_add_values_empty_returns_false(self, item_factory):
        item_factory(name="EmptyVal", category="EmptyValCat")
        assert add_values_to_item("EmptyVal", "", False) is False
        assert add_values_to_item("EmptyVal", "   ", False) is False

    def test_check_value_infinity(self, item_factory):
        item_factory(name="InfItem", category="InfCat", values=[("inf_val", True)])
        assert check_value("InfItem") is True

    def test_check_value_no_infinity(self, item_factory):
        item_factory(name="FinItem", category="FinCat", values=[("fin_val", False)])
        assert check_value("FinItem") is False

    def test_select_count_items(self, item_factory):
        item_factory(name="CI1", category="CICat", values=[("v1", False), ("v2", False)])
        assert select_count_items() == 2

    def test_select_count_goods(self, item_factory):
        item_factory(name="G1", category="GCat")
        item_factory(name="G2", category="GCat")
        assert select_count_goods() == 2

    def test_update_item_same_name(self, item_factory):
        item_factory(name="UpdItem", price=100, category="UpdCat", description="old desc")
        ok, err = update_item("UpdItem", "UpdItem", "new desc", 200, "UpdCat")
        assert ok is True
        assert err is None
        info = get_item_info("UpdItem")
        assert info["description"] == "new desc"
        assert info["price"] == Decimal("200")

    def test_update_item_rename(self, item_factory):
        item_factory(name="RenameOld", price=10, category="RenCat")
        ok, err = update_item("RenameOld", "RenameNew", "desc", 10, "RenCat")
        assert ok is True
        assert get_item_info("RenameOld") is None
        assert get_item_info("RenameNew") is not None

    def test_update_item_not_found(self):
        ok, err = update_item("Ghost", "Ghost2", "d", 1, "c")
        assert ok is False

    def test_delete_item(self, item_factory):
        item_factory(name="DelItem", category="DelCat", values=[("dv", False)])
        delete_item("DelItem")
        assert get_item_info("DelItem") is None
        assert select_item_values_amount("DelItem") == 0

    def test_delete_only_items(self, item_factory):
        item_factory(name="DelOnlyItem", category="DOCat", values=[("x", False)])
        delete_only_items("DelOnlyItem")
        assert get_item_info("DelOnlyItem") is not None
        assert select_item_values_amount("DelOnlyItem") == 0

    def test_delete_item_from_position(self, item_factory):
        item_factory(name="PosItem", category="PosCat", values=[("p1", False), ("p2", False)])
        # Get one item value id via DB
        from bot.database import Database as DB
        from bot.database.models import ItemValues
        with DB().session() as s:
            iv = s.query(ItemValues).filter(ItemValues.item_name == "PosItem").first()
            iv_id = iv.id
        delete_item_from_position(iv_id)
        assert select_item_values_amount("PosItem") == 1


class TestBalanceOperations:
    def test_update_balance(self, user_factory):
        user_factory(telegram_id=8001)
        update_balance(8001, 500)
        user = check_user(8001)
        assert user["balance"] == Decimal("500")

    def test_update_balance_multiple(self, user_factory):
        user_factory(telegram_id=8002)
        update_balance(8002, 100)
        update_balance(8002, 200)
        user = check_user(8002)
        assert user["balance"] == Decimal("300")

    def test_select_users_balance(self, user_factory):
        user_factory(telegram_id=8003, balance=100)
        user_factory(telegram_id=8004, balance=250)
        total = select_users_balance()
        assert total == Decimal("350")

    def test_create_operation(self, user_factory):
        user_factory(telegram_id=8005)
        create_operation(8005, 150, NOW)
        ops = select_user_operations(8005)
        assert len(ops) == 1
        assert ops[0] == Decimal("150")

    def test_select_user_operations_multiple(self, user_factory):
        user_factory(telegram_id=8006)
        create_operation(8006, 100, NOW)
        create_operation(8006, 200, NOW)
        ops = select_user_operations(8006)
        assert len(ops) == 2

    def test_select_today_operations(self, user_factory):
        user_factory(telegram_id=8007)
        create_operation(8007, 300, NOW)
        total = select_today_operations(TODAY_STR)
        assert total >= Decimal("300")

    def test_select_all_operations(self, user_factory):
        user_factory(telegram_id=8008)
        create_operation(8008, 400, NOW)
        total = select_all_operations()
        assert total >= Decimal("400")

    def test_set_user_blocked(self, user_factory):
        user_factory(telegram_id=8009)
        result = set_user_blocked(8009, True)
        assert result is True
        assert is_user_blocked(8009) is True

    def test_set_user_blocked_nonexistent(self):
        result = set_user_blocked(999777, True)
        assert result is False

    def test_is_user_blocked_default_false(self, user_factory):
        user_factory(telegram_id=8010)
        assert is_user_blocked(8010) is False

    def test_unblock_user(self, user_factory):
        user_factory(telegram_id=8011)
        set_user_blocked(8011, True)
        set_user_blocked(8011, False)
        assert is_user_blocked(8011) is False


class TestPayments:
    def test_create_pending_payment(self, user_factory):
        user_factory(telegram_id=9001)
        create_pending_payment("cryptopay", "ext_001", 9001, 500, "RUB")
        # Verify via direct DB query
        from bot.database import Database as DB
        from bot.database.models import Payments
        with DB().session() as s:
            p = s.query(Payments).filter(Payments.user_id == 9001).first()
            assert p is not None
            assert p.provider == "cryptopay"
            assert p.external_id == "ext_001"
            assert p.amount == Decimal("500")
            assert p.currency == "RUB"
            assert p.status == "pending"

    def test_create_multiple_payments(self, user_factory):
        user_factory(telegram_id=9002)
        create_pending_payment("stars", "ext_010", 9002, 100, "XTR")
        create_pending_payment("stars", "ext_011", 9002, 200, "XTR")
        from bot.database import Database as DB
        from bot.database.models import Payments
        with DB().session() as s:
            count = s.query(Payments).filter(Payments.user_id == 9002).count()
            assert count == 2


class TestReferrals:
    def test_check_user_referrals_count(self, user_factory):
        user_factory(telegram_id=10001)
        user_factory(telegram_id=10002, referral_id=10001)
        user_factory(telegram_id=10003, referral_id=10001)
        assert check_user_referrals(10001) == 2

    def test_check_user_referrals_zero(self, user_factory):
        user_factory(telegram_id=10004)
        assert check_user_referrals(10004) == 0

    def test_get_user_referral(self, user_factory):
        user_factory(telegram_id=10005)
        user_factory(telegram_id=10006, referral_id=10005)
        assert get_user_referral(10006) == 10005

    def test_get_user_referral_none(self, user_factory):
        user_factory(telegram_id=10007)
        assert get_user_referral(10007) is None

    def test_create_referral_earning(self, user_factory):
        user_factory(telegram_id=10008)
        user_factory(telegram_id=10009, referral_id=10008)
        create_referral_earning(10008, 10009, 50, 500)
        stats = get_referral_earnings_stats(10008)
        assert stats["total_earnings_count"] == 1
        assert stats["total_amount"] == Decimal("50")
        assert stats["total_original_amount"] == Decimal("500")
        assert stats["active_referrals_count"] == 1

    def test_get_one_referral_earning(self, user_factory):
        user_factory(telegram_id=10010)
        user_factory(telegram_id=10011, referral_id=10010)
        create_referral_earning(10010, 10011, 25, 250)
        # Get the earning id
        from bot.database import Database as DB
        from bot.database.models import ReferralEarnings
        with DB().session() as s:
            e = s.query(ReferralEarnings).filter(ReferralEarnings.referrer_id == 10010).first()
            eid = e.id
        earning = get_one_referral_earning(eid)
        assert earning is not None
        assert earning["referrer_id"] == 10010
        assert earning["amount"] == Decimal("25")

    def test_get_one_referral_earning_not_found(self):
        result = get_one_referral_earning(999999)
        assert result is None

    def test_referral_earnings_stats_empty(self, user_factory):
        user_factory(telegram_id=10012)
        stats = get_referral_earnings_stats(10012)
        assert stats["total_earnings_count"] == 0
        assert stats["total_amount"] == Decimal("0")


class TestStats:
    def test_select_today_orders_no_orders(self):
        total = select_today_orders(TODAY_STR)
        assert total == Decimal("0")

    def test_select_all_orders_no_orders(self):
        total = select_all_orders()
        assert total == Decimal("0")

    def test_select_today_orders_with_bought_goods(self, user_factory):
        user_factory(telegram_id=11001)
        from bot.database import Database as DB
        from bot.database.models import BoughtGoods
        with DB().session() as s:
            s.add(BoughtGoods(
                name="Sold1", value="val", price=150,
                bought_datetime=NOW, unique_id=90001, buyer_id=11001,
            ))
        total = select_today_orders(TODAY_STR)
        assert total == Decimal("150")

    def test_select_all_orders_with_bought_goods(self, user_factory):
        user_factory(telegram_id=11002)
        from bot.database import Database as DB
        from bot.database.models import BoughtGoods
        with DB().session() as s:
            s.add(BoughtGoods(
                name="SoldA", value="v1", price=100,
                bought_datetime=NOW, unique_id=90002, buyer_id=11002,
            ))
            s.add(BoughtGoods(
                name="SoldB", value="v2", price=200,
                bought_datetime=NOW, unique_id=90003, buyer_id=11002,
            ))
        total = select_all_orders()
        assert total == Decimal("300")

    def test_select_user_items_count(self, user_factory):
        user_factory(telegram_id=11003)
        from bot.database import Database as DB
        from bot.database.models import BoughtGoods
        with DB().session() as s:
            s.add(BoughtGoods(
                name="B1", value="v", price=10,
                bought_datetime=NOW, unique_id=90004, buyer_id=11003,
            ))
            s.add(BoughtGoods(
                name="B2", value="v", price=20,
                bought_datetime=NOW, unique_id=90005, buyer_id=11003,
            ))
        assert select_user_items(11003) == 2

    def test_select_users_balance_empty(self):
        total = select_users_balance()
        # No users, so None or 0
        assert total is None or total == Decimal("0")

    def test_select_all_operations_empty(self):
        assert select_all_operations() == Decimal("0")

    def test_select_today_operations_empty(self):
        assert select_today_operations(TODAY_STR) == Decimal("0")
