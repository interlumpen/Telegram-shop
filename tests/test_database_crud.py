import datetime
from decimal import Decimal

from sqlalchemy import select

from bot.database.methods.create import (
    create_user, create_item, add_values_to_item,
    create_operation, create_pending_payment, create_referral_earning,
)
from bot.database.methods.read import (
    check_user, check_role, get_role_id_by_name,
    check_role_name_by_id, select_max_role_id,
    select_today_users, get_user_count,
    get_all_users, check_category,
    get_item_info, check_value,
    select_item_values_amount,
    select_count_items, select_count_goods,
    select_count_categories, select_user_items,
    select_user_operations,
    check_user_referrals, get_user_referral,
    get_referral_earnings_stats,
    get_one_referral_earning,
    select_today_orders, select_all_orders,
    select_today_operations, select_all_operations,
    select_users_balance,
    get_all_roles, get_role_by_id, get_roles_with_max_perms,
    count_users_with_role,
)
from bot.database.methods.update import (
    update_balance, set_role, set_user_blocked,
    is_user_blocked, update_item, update_category,
)
from bot.database.methods.delete import (
    delete_item, delete_only_items,
    delete_item_from_position, delete_category,
)


NOW = datetime.datetime.now(datetime.timezone.utc)
TODAY_STR = NOW.strftime("%Y-%m-%d")


class TestUserCRUD:
    async def test_create_user_and_check(self, user_factory):
        user = await user_factory(telegram_id=1001)
        assert user is not None
        assert user["telegram_id"] == 1001

    async def test_create_user_duplicate_ignored(self, user_factory):
        await user_factory(telegram_id=2001)
        # Creating again should not raise
        await create_user(2001, NOW, referral_id=None, role=1)
        assert await get_user_count() == 1

    async def test_check_user_not_found(self):
        result = await check_user(999999)
        assert result is None

    async def test_get_user_count(self, user_factory):
        assert await get_user_count() == 0
        await user_factory(telegram_id=3001)
        await user_factory(telegram_id=3002)
        assert await get_user_count() == 2

    async def test_get_all_users(self, user_factory):
        await user_factory(telegram_id=4001)
        await user_factory(telegram_id=4002)
        users = await get_all_users()
        ids = [row[0] for row in users]
        assert 4001 in ids
        assert 4002 in ids

    async def test_select_today_users(self, user_factory):
        await user_factory(telegram_id=5001)
        count = await select_today_users(TODAY_STR)
        assert count >= 1

    async def test_select_today_users_wrong_date(self, user_factory):
        await user_factory(telegram_id=5002)
        count = await select_today_users("2000-01-01")
        assert count == 0

    async def test_create_user_with_referral(self, user_factory):
        await user_factory(telegram_id=6001)
        await user_factory(telegram_id=6002, referral_id=6001)
        ref = await get_user_referral(6002)
        assert ref == 6001


class TestRoleCRUD:
    async def test_get_role_id_by_name_user(self):
        role_id = await get_role_id_by_name("USER")
        assert role_id is not None

    async def test_get_role_id_by_name_admin(self):
        role_id = await get_role_id_by_name("ADMIN")
        assert role_id is not None

    async def test_get_role_id_by_name_nonexistent(self):
        role_id = await get_role_id_by_name("NONEXISTENT")
        assert role_id is None

    async def test_check_role_name_by_id(self):
        role_id = await get_role_id_by_name("USER")
        name = await check_role_name_by_id(role_id)
        assert name == "USER"

    async def test_select_max_role_id(self):
        max_id = await select_max_role_id()
        assert max_id is not None
        assert max_id >= 1

    async def test_check_role_returns_permissions(self, user_factory):
        await user_factory(telegram_id=7001)
        perms = await check_role(7001)
        # USER role has USE=1 permission
        assert perms & 1 == 1

    async def test_check_role_nonexistent_user(self):
        perms = await check_role(999888)
        assert perms == 0

    async def test_set_role(self, user_factory):
        await user_factory(telegram_id=7002)
        admin_role_id = await get_role_id_by_name("ADMIN")
        await set_role(7002, admin_role_id)
        perms = await check_role(7002)
        # ADMIN has BROADCAST=2 permission
        assert perms & 2 == 2

    async def test_get_all_roles(self):
        roles = await get_all_roles()
        assert len(roles) >= 3
        assert all(k in roles[0] for k in ('id', 'name', 'permissions', 'default'))

    async def test_get_role_by_id(self):
        role_id = await get_role_id_by_name('ADMIN')
        role = await get_role_by_id(role_id)
        assert role['name'] == 'ADMIN'

    async def test_get_roles_with_max_perms(self):
        roles = await get_roles_with_max_perms(1)
        assert all((r['permissions'] & ~1) == 0 for r in roles)

    async def test_count_users_with_role(self, user_factory):
        await user_factory(telegram_id=7003, role_id=1)
        user_role = await get_role_id_by_name('USER')
        assert await count_users_with_role(user_role) >= 1


class TestCategoryCRUD:
    async def test_create_and_check_category(self, category_factory):
        await category_factory("Electronics")
        cat = await check_category("Electronics")
        assert cat is not None
        assert cat["name"] == "Electronics"

    async def test_create_category_duplicate_ignored(self, category_factory):
        await category_factory("Books")
        await category_factory("Books")
        assert await select_count_categories() == 1

    async def test_check_category_not_found(self):
        assert await check_category("Nonexistent") is None

    async def test_select_count_categories(self, category_factory):
        await category_factory("CatA")
        await category_factory("CatB")
        assert await select_count_categories() == 2

    async def test_update_category_rename(self, category_factory):
        await category_factory("OldCat")
        await update_category("OldCat", "NewCat")
        assert await check_category("OldCat") is None
        assert await check_category("NewCat") is not None

    async def test_delete_category(self, category_factory):
        await category_factory("ToDelete")
        await delete_category("ToDelete")
        assert await check_category("ToDelete") is None


class TestItemCRUD:
    async def test_create_and_get_item_info(self, item_factory):
        await item_factory(name="Widget", price=50, category="Gadgets")
        item = await get_item_info("Widget")
        assert item is not None
        assert item["name"] == "Widget"
        assert item["price"] == Decimal("50")

    async def test_get_item_info(self, item_factory):
        await item_factory(name="InfoItem", price=75, category="InfoCat", description="Desc here")
        info = await get_item_info("InfoItem")
        assert info is not None
        assert info["description"] == "Desc here"

    async def test_create_item_duplicate_ignored(self, item_factory):
        await item_factory(name="DupItem", category="DupCat")
        await create_item("DupItem", "desc2", 200, "DupCat")
        assert await select_count_goods() == 1

    async def test_add_values_to_item(self, item_factory):
        await item_factory(name="ValItem", category="ValCat")
        result = await add_values_to_item("ValItem", "code123", False)
        assert result is True
        assert await select_item_values_amount("ValItem") == 1

    async def test_add_values_duplicate_returns_false(self, item_factory):
        await item_factory(name="DupVal", category="DupValCat")
        await add_values_to_item("DupVal", "abc", False)
        result = await add_values_to_item("DupVal", "abc", False)
        assert result is False

    async def test_add_values_empty_returns_false(self, item_factory):
        await item_factory(name="EmptyVal", category="EmptyValCat")
        assert await add_values_to_item("EmptyVal", "", False) is False
        assert await add_values_to_item("EmptyVal", "   ", False) is False

    async def test_check_value_infinity(self, item_factory):
        await item_factory(name="InfItem", category="InfCat", values=[("inf_val", True)])
        assert await check_value("InfItem") is True

    async def test_check_value_no_infinity(self, item_factory):
        await item_factory(name="FinItem", category="FinCat", values=[("fin_val", False)])
        assert await check_value("FinItem") is False

    async def test_select_count_items(self, item_factory):
        await item_factory(name="CI1", category="CICat", values=[("v1", False), ("v2", False)])
        assert await select_count_items() == 2

    async def test_select_count_goods(self, item_factory):
        await item_factory(name="G1", category="GCat")
        await item_factory(name="G2", category="GCat")
        assert await select_count_goods() == 2

    async def test_update_item_same_name(self, item_factory):
        await item_factory(name="UpdItem", price=100, category="UpdCat", description="old desc")
        ok, err = await update_item("UpdItem", "UpdItem", "new desc", 200, "UpdCat")
        assert ok is True
        assert err is None
        info = await get_item_info("UpdItem")
        assert info["description"] == "new desc"
        assert info["price"] == Decimal("200")

    async def test_update_item_rename(self, item_factory):
        await item_factory(name="RenameOld", price=10, category="RenCat")
        ok, err = await update_item("RenameOld", "RenameNew", "desc", 10, "RenCat")
        assert ok is True
        assert await get_item_info("RenameOld") is None
        assert await get_item_info("RenameNew") is not None

    async def test_update_item_not_found(self):
        ok, err = await update_item("Ghost", "Ghost2", "d", 1, "c")
        assert ok is False

    async def test_delete_item(self, item_factory):
        await item_factory(name="DelItem", category="DelCat", values=[("dv", False)])
        await delete_item("DelItem")
        assert await get_item_info("DelItem") is None
        assert await select_item_values_amount("DelItem") == 0

    async def test_delete_only_items(self, item_factory):
        await item_factory(name="DelOnlyItem", category="DOCat", values=[("x", False)])
        await delete_only_items("DelOnlyItem")
        assert await get_item_info("DelOnlyItem") is not None
        assert await select_item_values_amount("DelOnlyItem") == 0

    async def test_delete_item_from_position(self, item_factory):
        await item_factory(name="PosItem", category="PosCat", values=[("p1", False), ("p2", False)])
        # Get one item value id via async DB session
        from bot.database import Database as DB
        from bot.database.models import ItemValues
        from bot.database.models.main import Goods
        async with DB().session() as s:
            result = await s.execute(select(Goods).where(Goods.name == "PosItem"))
            pos = result.scalars().first()
            result = await s.execute(select(ItemValues).where(ItemValues.item_id == pos.id))
            iv = result.scalars().first()
            iv_id = iv.id
        await delete_item_from_position(iv_id)
        assert await select_item_values_amount("PosItem") == 1


class TestBalanceOperations:
    async def test_update_balance(self, user_factory):
        await user_factory(telegram_id=8001)
        await update_balance(8001, 500)
        user = await check_user(8001)
        assert user["balance"] == Decimal("500")

    async def test_update_balance_multiple(self, user_factory):
        await user_factory(telegram_id=8002)
        await update_balance(8002, 100)
        await update_balance(8002, 200)
        user = await check_user(8002)
        assert user["balance"] == Decimal("300")

    async def test_select_users_balance(self, user_factory):
        await user_factory(telegram_id=8003, balance=100)
        await user_factory(telegram_id=8004, balance=250)
        total = await select_users_balance()
        assert total == Decimal("350")

    async def test_create_operation(self, user_factory):
        await user_factory(telegram_id=8005)
        await create_operation(8005, 150, NOW)
        ops = await select_user_operations(8005)
        assert len(ops) == 1
        assert ops[0] == Decimal("150")

    async def test_select_user_operations_multiple(self, user_factory):
        await user_factory(telegram_id=8006)
        await create_operation(8006, 100, NOW)
        await create_operation(8006, 200, NOW)
        ops = await select_user_operations(8006)
        assert len(ops) == 2

    async def test_select_today_operations(self, user_factory):
        await user_factory(telegram_id=8007)
        await create_operation(8007, 300, NOW)
        total = await select_today_operations(TODAY_STR)
        assert total >= Decimal("300")

    async def test_select_all_operations(self, user_factory):
        await user_factory(telegram_id=8008)
        await create_operation(8008, 400, NOW)
        total = await select_all_operations()
        assert total >= Decimal("400")

    async def test_set_user_blocked(self, user_factory):
        await user_factory(telegram_id=8009)
        result = await set_user_blocked(8009, True)
        assert result is True
        assert await is_user_blocked(8009) is True

    async def test_set_user_blocked_nonexistent(self):
        result = await set_user_blocked(999777, True)
        assert result is False

    async def test_is_user_blocked_default_false(self, user_factory):
        await user_factory(telegram_id=8010)
        assert await is_user_blocked(8010) is False

    async def test_unblock_user(self, user_factory):
        await user_factory(telegram_id=8011)
        await set_user_blocked(8011, True)
        await set_user_blocked(8011, False)
        assert await is_user_blocked(8011) is False


class TestPayments:
    async def test_create_pending_payment(self, user_factory):
        await user_factory(telegram_id=9001)
        await create_pending_payment("cryptopay", "ext_001", 9001, 500, "RUB")
        # Verify via async DB query
        from bot.database import Database as DB
        from bot.database.models import Payments
        async with DB().session() as s:
            result = await s.execute(select(Payments).where(Payments.user_id == 9001))
            p = result.scalars().first()
            assert p is not None
            assert p.provider == "cryptopay"
            assert p.external_id == "ext_001"
            assert p.amount == Decimal("500")
            assert p.currency == "RUB"
            assert p.status == "pending"

    async def test_create_multiple_payments(self, user_factory):
        await user_factory(telegram_id=9002)
        await create_pending_payment("stars", "ext_010", 9002, 100, "XTR")
        await create_pending_payment("stars", "ext_011", 9002, 200, "XTR")
        from bot.database import Database as DB
        from bot.database.models import Payments
        async with DB().session() as s:
            from sqlalchemy import func
            result = await s.execute(
                select(func.count()).select_from(Payments).where(Payments.user_id == 9002)
            )
            count = result.scalar()
            assert count == 2


class TestReferrals:
    async def test_check_user_referrals_count(self, user_factory):
        await user_factory(telegram_id=10001)
        await user_factory(telegram_id=10002, referral_id=10001)
        await user_factory(telegram_id=10003, referral_id=10001)
        assert await check_user_referrals(10001) == 2

    async def test_check_user_referrals_zero(self, user_factory):
        await user_factory(telegram_id=10004)
        assert await check_user_referrals(10004) == 0

    async def test_get_user_referral(self, user_factory):
        await user_factory(telegram_id=10005)
        await user_factory(telegram_id=10006, referral_id=10005)
        assert await get_user_referral(10006) == 10005

    async def test_get_user_referral_none(self, user_factory):
        await user_factory(telegram_id=10007)
        assert await get_user_referral(10007) is None

    async def test_create_referral_earning(self, user_factory):
        await user_factory(telegram_id=10008)
        await user_factory(telegram_id=10009, referral_id=10008)
        await create_referral_earning(10008, 10009, 50, 500)
        stats = await get_referral_earnings_stats(10008)
        assert stats["total_earnings_count"] == 1
        assert stats["total_amount"] == Decimal("50")
        assert stats["total_original_amount"] == Decimal("500")
        assert stats["active_referrals_count"] == 1

    async def test_get_one_referral_earning(self, user_factory):
        await user_factory(telegram_id=10010)
        await user_factory(telegram_id=10011, referral_id=10010)
        await create_referral_earning(10010, 10011, 25, 250)
        # Get the earning id via async DB session
        from bot.database import Database as DB
        from bot.database.models import ReferralEarnings
        async with DB().session() as s:
            result = await s.execute(
                select(ReferralEarnings).where(ReferralEarnings.referrer_id == 10010)
            )
            e = result.scalars().first()
            eid = e.id
        earning = await get_one_referral_earning(eid)
        assert earning is not None
        assert earning["referrer_id"] == 10010
        assert earning["amount"] == Decimal("25")

    async def test_get_one_referral_earning_not_found(self):
        result = await get_one_referral_earning(999999)
        assert result is None

    async def test_referral_earnings_stats_empty(self, user_factory):
        await user_factory(telegram_id=10012)
        stats = await get_referral_earnings_stats(10012)
        assert stats["total_earnings_count"] == 0
        assert stats["total_amount"] == Decimal("0")


class TestStats:
    async def test_select_today_orders_no_orders(self):
        total = await select_today_orders(TODAY_STR)
        assert total == Decimal("0")

    async def test_select_all_orders_no_orders(self):
        total = await select_all_orders()
        assert total == Decimal("0")

    async def test_select_today_orders_with_bought_goods(self, user_factory):
        await user_factory(telegram_id=11001)
        from bot.database import Database as DB
        from bot.database.models import BoughtGoods
        async with DB().session() as s:
            s.add(BoughtGoods(
                name="Sold1", value="val", price=150,
                bought_datetime=NOW, unique_id=90001, buyer_id=11001,
            ))
        total = await select_today_orders(TODAY_STR)
        assert total == Decimal("150")

    async def test_select_all_orders_with_bought_goods(self, user_factory):
        await user_factory(telegram_id=11002)
        from bot.database import Database as DB
        from bot.database.models import BoughtGoods
        async with DB().session() as s:
            s.add(BoughtGoods(
                name="SoldA", value="v1", price=100,
                bought_datetime=NOW, unique_id=90002, buyer_id=11002,
            ))
            s.add(BoughtGoods(
                name="SoldB", value="v2", price=200,
                bought_datetime=NOW, unique_id=90003, buyer_id=11002,
            ))
        total = await select_all_orders()
        assert total == Decimal("300")

    async def test_select_user_items_count(self, user_factory):
        await user_factory(telegram_id=11003)
        from bot.database import Database as DB
        from bot.database.models import BoughtGoods
        async with DB().session() as s:
            s.add(BoughtGoods(
                name="B1", value="v", price=10,
                bought_datetime=NOW, unique_id=90004, buyer_id=11003,
            ))
            s.add(BoughtGoods(
                name="B2", value="v", price=20,
                bought_datetime=NOW, unique_id=90005, buyer_id=11003,
            ))
        assert await select_user_items(11003) == 2

    async def test_select_users_balance_empty(self):
        total = await select_users_balance()
        # No users, so None or 0
        assert total is None or total == Decimal("0")

    async def test_select_all_operations_empty(self):
        assert await select_all_operations() == Decimal("0")

    async def test_select_today_operations_empty(self):
        assert await select_today_operations(TODAY_STR) == Decimal("0")
