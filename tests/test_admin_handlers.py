import pytest
from decimal import Decimal
from unittest.mock import patch, MagicMock, AsyncMock

from bot.database.methods.read import (
    check_user, get_role_id_by_name, check_role_name_by_id, select_max_role_id,
    get_item_info, select_item_values_amount, check_value,
)
from bot.database.methods.transactions import replace_item_stock_and_meta
from bot.database.methods.update import update_item
from bot.handlers.admin.categories_management import (
    process_category_for_add, process_category_for_delete,
    check_category_for_update, check_category_name_for_update,
)
from bot.handlers.admin.goods_management import delete_str_item, show_str_item
from bot.handlers.admin.role_management import assign_role_confirm
from bot.handlers.admin.update_position import check_item_name_for_update
from bot.handlers.admin.user_management import (
    check_user_data, block_user_handler, unblock_user_handler,
    process_replenish_user_balance, process_deduct_user_balance,
)

class TestCheckUserData:

    async def test_check_valid_user(self, make_message, fsm_context, user_factory):

        await user_factory(telegram_id=800001, balance=500)

        msg = make_message(text="800001", user_id=900001)
        await fsm_context.set_state("waiting_user_id_for_check")

        await check_user_data(msg, fsm_context)

        msg.answer.assert_called_once()
        text = msg.answer.call_args[0][0]
        assert "800001" in text

    async def test_check_invalid_user_id(self, make_message, fsm_context):

        msg = make_message(text="not_a_number", user_id=900002)

        await check_user_data(msg, fsm_context)

        msg.answer.assert_called_once()
        text = msg.answer.call_args[0][0]
        assert "invalid_id" in text

    async def test_check_nonexistent_user(self, make_message, fsm_context):

        msg = make_message(text="999888777", user_id=900003)

        await check_user_data(msg, fsm_context)

        msg.answer.assert_called_once()
        text = msg.answer.call_args[0][0]
        assert "unavailable" in text


class TestAssignRole:

    async def test_assign_role(self, make_callback_query, user_factory):

        await user_factory(telegram_id=800010, role_id=1)
        admin_role = await get_role_id_by_name('ADMIN')

        call = make_callback_query(data=f"asr_{admin_role}_800010", user_id=900010)

        with patch('bot.handlers.admin.role_management.check_role_cached', new_callable=AsyncMock, return_value=1023):
            await assign_role_confirm(call)

        call.message.edit_text.assert_called_once()
        user = await check_user(800010)
        assert user['role_id'] == admin_role

    async def test_assign_user_role(self, make_callback_query, user_factory):

        admin_role = await get_role_id_by_name('ADMIN')
        user_role = await get_role_id_by_name('USER')
        await user_factory(telegram_id=800011, role_id=admin_role)

        call = make_callback_query(data=f"asr_{user_role}_800011", user_id=900011)

        with patch('bot.handlers.admin.role_management.check_role_cached', new_callable=AsyncMock, return_value=127):
            await assign_role_confirm(call)

        call.message.edit_text.assert_called_once()
        user = await check_user(800011)
        assert user['role_id'] == user_role

    async def test_cannot_change_owner_role(self, make_callback_query, user_factory):

        max_role = await select_max_role_id()
        await user_factory(telegram_id=800012, role_id=max_role)
        admin_role = await get_role_id_by_name('ADMIN')

        call = make_callback_query(data=f"asr_{admin_role}_800012", user_id=900012)

        with patch('bot.handlers.admin.role_management.check_role_cached', new_callable=AsyncMock, return_value=127):
            await assign_role_confirm(call)

        call.answer.assert_called_once()
        # Role should not change
        user = await check_user(800012)
        assert user['role_id'] == max_role


class TestReplenishBalance:

    async def test_replenish_user_balance(self, make_message, fsm_context, user_factory):

        await user_factory(telegram_id=800020, balance=100)
        await fsm_context.update_data(target_user=800020)

        msg = make_message(text="500", user_id=900020)

        await process_replenish_user_balance(msg, fsm_context)

        msg.answer.assert_called_once()
        user = await check_user(800020)
        assert user['balance'] == Decimal("600")

    async def test_deduct_user_balance(self, make_message, fsm_context, user_factory):

        await user_factory(telegram_id=800021, balance=500)
        await fsm_context.update_data(target_user=800021)

        msg = make_message(text="200", user_id=900021)

        await process_deduct_user_balance(msg, fsm_context)

        msg.answer.assert_called_once()
        user = await check_user(800021)
        assert user['balance'] == Decimal("300")

    async def test_deduct_insufficient_balance(self, make_message, fsm_context, user_factory):

        await user_factory(telegram_id=800022, balance=50)
        await fsm_context.update_data(target_user=800022)

        msg = make_message(text="200", user_id=900022)

        await process_deduct_user_balance(msg, fsm_context)

        msg.answer.assert_called_once()
        # Balance should not change
        user = await check_user(800022)
        assert user['balance'] == Decimal("50")


class TestBlockUser:

    async def test_block_user(self, make_callback_query, user_factory):

        await user_factory(telegram_id=800030, role_id=1)

        call = make_callback_query(data="block-user_800030", user_id=900030)

        mock_auth = MagicMock()
        mock_auth.block_user = AsyncMock(return_value=True)

        with patch('bot.middleware.security._auth_middleware_instance', mock_auth):
            await block_user_handler(call)

        call.message.edit_text.assert_called_once()
        mock_auth.block_user.assert_called_once_with(800030)

    async def test_unblock_user(self, make_callback_query, user_factory):

        await user_factory(telegram_id=800031, role_id=1)

        call = make_callback_query(data="unblock-user_800031", user_id=900031)

        mock_auth = MagicMock()
        mock_auth.unblock_user = AsyncMock(return_value=True)

        with patch('bot.middleware.security._auth_middleware_instance', mock_auth):
            await unblock_user_handler(call)

        call.message.edit_text.assert_called_once()
        mock_auth.unblock_user.assert_called_once_with(800031)

    async def test_cannot_block_owner(self, make_callback_query, user_factory):

        max_role = await select_max_role_id()
        await user_factory(telegram_id=800032, role_id=max_role)

        call = make_callback_query(data="block-user_800032", user_id=900032)

        await block_user_handler(call)

        call.answer.assert_called_once()


class TestReplenishBalanceEdgeCases:

    async def test_replenish_non_numeric_input(self, make_message, fsm_context, user_factory):

        await user_factory(telegram_id=800040, balance=100)
        await fsm_context.update_data(target_user=800040)

        msg = make_message(text="abc", user_id=900060)

        await process_replenish_user_balance(msg, fsm_context)

        msg.answer.assert_called_once()
        # Balance should not change
        user = await check_user(800040)
        assert user['balance'] == Decimal("100")

    async def test_replenish_negative_amount(self, make_message, fsm_context, user_factory):

        await user_factory(telegram_id=800041, balance=100)
        await fsm_context.update_data(target_user=800041)

        msg = make_message(text="-500", user_id=900061)

        await process_replenish_user_balance(msg, fsm_context)

        msg.answer.assert_called_once()
        user = await check_user(800041)
        assert user['balance'] == Decimal("100")

    async def test_replenish_zero_amount(self, make_message, fsm_context, user_factory):

        await user_factory(telegram_id=800042, balance=100)
        await fsm_context.update_data(target_user=800042)

        msg = make_message(text="0", user_id=900062)

        await process_replenish_user_balance(msg, fsm_context)

        msg.answer.assert_called_once()


class TestCategoryManagement:

    async def test_add_category(self, make_message, fsm_context):

        msg = make_message(text="NewCategory", user_id=900040)

        await process_category_for_add(msg, fsm_context)

        msg.answer.assert_called_once()
        text = msg.answer.call_args[0][0]
        assert "success" in text

    async def test_add_duplicate_category(self, make_message, fsm_context, category_factory):

        await category_factory("ExistingCat")

        msg = make_message(text="ExistingCat", user_id=900041)

        await process_category_for_add(msg, fsm_context)

        msg.answer.assert_called_once()
        text = msg.answer.call_args[0][0]
        assert "exist" in text

    async def test_delete_category(self, make_message, fsm_context, category_factory):

        await category_factory("ToDelete")

        msg = make_message(text="ToDelete", user_id=900042)

        await process_category_for_delete(msg, fsm_context)

        msg.answer.assert_called_once()
        text = msg.answer.call_args[0][0]
        assert "success" in text

    async def test_delete_nonexistent_category(self, make_message, fsm_context):

        msg = make_message(text="NoSuchCat", user_id=900043)

        await process_category_for_delete(msg, fsm_context)

        msg.answer.assert_called_once()
        text = msg.answer.call_args[0][0]
        assert "not_found" in text

    async def test_rename_category(self, make_message, fsm_context, category_factory):

        await category_factory("OldName")

        # Step 1: enter old name
        msg1 = make_message(text="OldName", user_id=900044)
        await check_category_for_update(msg1, fsm_context)

        # Step 2: enter new name
        msg2 = make_message(text="NewName", user_id=900044)
        await check_category_name_for_update(msg2, fsm_context)

        msg2.answer.assert_called_once()
        text = msg2.answer.call_args[0][0]
        assert "success" in text


class TestGoodsManagement:

    async def test_delete_item(self, make_message, fsm_context, item_factory):

        await item_factory(name="ToDeleteItem", price=100, category="DelCat", values=[("v1", False)])

        msg = make_message(text="ToDeleteItem", user_id=900050)

        await delete_str_item(msg, fsm_context)

        msg.answer.assert_called_once()
        text = msg.answer.call_args[0][0]
        assert "success" in text

        # Verify item deleted
        item = await get_item_info("ToDeleteItem")
        assert item is None

    async def test_delete_item_not_found(self, make_message, fsm_context):

        msg = make_message(text="NoSuchItem", user_id=900051)

        await delete_str_item(msg, fsm_context)

        msg.answer.assert_called_once()
        text = msg.answer.call_args[0][0]
        assert "not_found" in text

    async def test_show_items_not_found(self, make_message, fsm_context):

        msg = make_message(text="NoItem", user_id=900052)

        await show_str_item(msg, fsm_context)

        msg.answer.assert_called_once()
        text = msg.answer.call_args[0][0]
        assert "not_found" in text


class TestUpdateItemFlow:
    async def test_update_flow_stores_category_name_not_id(self, make_message, fsm_context, item_factory):

        await item_factory(name="UpdMe", price=10, category="MyCat", values=[("v", False)])
        msg = make_message(text="UpdMe", user_id=900060)

        await check_item_name_for_update(msg, fsm_context)

        data = await fsm_context.get_data()
        assert data["item_category"] == "MyCat"

        ok, err = await update_item("UpdMe", "UpdMe", "new desc", 20, data["item_category"])
        assert (ok, err) == (True, None)


class TestAtomicStockReplacement:
    async def test_failed_rename_leaves_stock_untouched(self, item_factory):

        await item_factory(name="KeepStock", price=100, category="AtomCat",
                           values=[("a", False), ("b", False), ("c", False)])
        # The new name is already taken, so the meta update must fail.
        await item_factory(name="Occupied", price=50, category="AtomCat")

        ok, err, added = await replace_item_stock_and_meta(
            old_name="KeepStock", new_name="Occupied", description="d",
            price=100, category_name="AtomCat", values=["x"], is_infinity=True,
        )

        assert (ok, err, added) == (False, "position_exists", 0)
        # Nothing changed: the stock is intact and the name is unchanged.
        assert await select_item_values_amount("KeepStock") == 3
        assert await get_item_info("KeepStock") is not None

    async def test_unknown_category_is_rejected_before_any_write(self, item_factory):

        await item_factory(name="CatGuard", price=10, category="AtomCat2",
                           values=[("a", False), ("b", False)])

        ok, err, _ = await replace_item_stock_and_meta(
            old_name="CatGuard", new_name="CatGuard", description="d",
            price=10, category_name="NoSuchCategory", values=["x"], is_infinity=False,
        )

        assert (ok, err) == (False, "position_invalid")
        assert await select_item_values_amount("CatGuard") == 2

    async def test_success_replaces_stock_and_renames(self, item_factory):

        await item_factory(name="ToInfinite", price=100, category="AtomCat3",
                           values=[("a", False), ("b", False)])

        ok, err, added = await replace_item_stock_and_meta(
            old_name="ToInfinite", new_name="NowInfinite", description="new desc",
            price=250, category_name="AtomCat3", values=["forever"], is_infinity=True,
        )

        assert (ok, err, added) == (True, None, 1)
        assert await get_item_info("ToInfinite") is None
        info = await get_item_info("NowInfinite")
        assert info["description"] == "new desc"
        assert int(info["price"]) == 250
        # Exactly one row, and it is the infinite one.
        assert await select_item_values_amount("NowInfinite") == 1
        assert await check_value("NowInfinite") is True

    async def test_duplicates_and_blanks_are_dropped(self, item_factory):

        await item_factory(name="DedupStock", price=10, category="AtomCat4", values=[])

        ok, err, added = await replace_item_stock_and_meta(
            old_name="DedupStock", new_name="DedupStock", description="d",
            price=10, category_name="AtomCat4",
            values=["a", "a", "  ", "b", "", " b "], is_infinity=False,
        )

        assert (ok, err) == (True, None)
        assert added == 2
        assert await select_item_values_amount("DedupStock") == 2


class TestStatsAggregates:
    async def _stats_cache(self, fake_cache):
        from bot.misc.caching.stats_cache import StatsCache
        return StatsCache(fake_cache)

    async def test_global_stats_counts_every_table(
        self, fake_cache, user_factory, item_factory
    ):
        await user_factory(telegram_id=930001)
        await user_factory(telegram_id=930002)
        await item_factory(
            name="StatItem", price=100, category="StatCat",
            values=[("a", False), ("b", False)],
        )
        await item_factory(name="StatItem2", price=50, category="StatCat", values=[])

        stats = await (await self._stats_cache(fake_cache)).get_global_stats()

        assert stats["total_users"] == 2
        assert stats["total_goods"] == 2
        assert stats["total_items"] == 2  # stock rows, not positions
        assert stats["total_revenue"] == Decimal(0)

    async def test_global_revenue_sums_purchases(
        self, fake_cache, user_factory, item_factory
    ):
        from bot.database.methods.transactions import buy_item_transaction

        await user_factory(telegram_id=930003, balance=1000)
        await item_factory(
            name="SoldItem", price=150, category="StatCat2",
            values=[("v1", False), ("v2", False)],
        )

        assert (await buy_item_transaction(930003, "SoldItem"))[0] is True
        assert (await buy_item_transaction(930003, "SoldItem"))[0] is True

        stats = await (await self._stats_cache(fake_cache)).get_global_stats()

        assert stats["total_revenue"] == Decimal("300.00")
        # Both stock rows were consumed.
        assert stats["total_items"] == 0

    async def test_daily_stats_respects_the_day_window(
        self, fake_cache, user_factory
    ):
        import datetime as _dt
        from bot.database.main import Database
        from bot.database.models.main import Operations

        await user_factory(telegram_id=930004)

        today = _dt.datetime.now(_dt.timezone.utc)
        yesterday = today - _dt.timedelta(days=1)

        async with Database().session() as s:
            s.add(Operations(user_id=930004, operation_value=Decimal("70.00"),
                             operation_time=today))
            s.add(Operations(user_id=930004, operation_value=Decimal("500.00"),
                             operation_time=yesterday))

        stats = await (await self._stats_cache(fake_cache)).get_daily_stats(
            today.date().isoformat()
        )

        # Yesterday's 500 must not leak into today's figure.
        assert stats["operations"] == Decimal("70.00")
        assert stats["users"] == 1
        assert stats["orders"] == Decimal(0)

    async def test_daily_stats_are_zero_on_an_empty_day(self, fake_cache):
        stats = await (await self._stats_cache(fake_cache)).get_daily_stats("2020-01-01")

        assert stats == {
            "users": 0,
            "orders": Decimal(0),
            "operations": Decimal(0),
            "orders_count": 0,
        }


class TestStatisticsScreen:

    async def test_renders_with_the_stats_cache(
        self, make_callback_query, fake_cache, user_factory, item_factory
    ):
        from bot.handlers.admin import shop_management
        from bot.misc.caching.stats_cache import StatsCache

        await user_factory(telegram_id=931001)
        await item_factory(name="ScreenItem", price=100, category="ScreenCat",
                           values=[("x", False)])

        call = make_callback_query(data="statistics", user_id=931001)
        with patch.object(shop_management, "stats_cache", StatsCache(fake_cache)):
            await shop_management.statistics_callback_handler(call)

        call.message.edit_text.assert_called_once()

    async def test_renders_without_the_stats_cache(
        self, make_callback_query, fake_cache, user_factory
    ):
        from bot.handlers.admin import shop_management

        await user_factory(telegram_id=931002)

        call = make_callback_query(data="statistics", user_id=931002)
        with patch.object(shop_management, "stats_cache", None):
            await shop_management.statistics_callback_handler(call)

        call.message.edit_text.assert_called_once()
