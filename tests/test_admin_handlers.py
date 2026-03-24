import pytest
from decimal import Decimal
from unittest.mock import patch, MagicMock, AsyncMock

from bot.database.methods.read import check_user, get_role_id_by_name, check_role_name_by_id, select_max_role_id, get_item_info

class TestCheckUserData:

    async def test_check_valid_user(self, make_message, fsm_context, user_factory):
        from bot.handlers.admin.user_management_states import check_user_data

        await user_factory(telegram_id=800001, balance=500)

        msg = make_message(text="800001", user_id=900001)
        await fsm_context.set_state("waiting_user_id_for_check")

        await check_user_data(msg, fsm_context)

        msg.answer.assert_called_once()
        text = msg.answer.call_args[0][0]
        assert "800001" in text

    async def test_check_invalid_user_id(self, make_message, fsm_context):
        from bot.handlers.admin.user_management_states import check_user_data

        msg = make_message(text="not_a_number", user_id=900002)

        await check_user_data(msg, fsm_context)

        msg.answer.assert_called_once()
        text = msg.answer.call_args[0][0]
        assert "invalid_id" in text

    async def test_check_nonexistent_user(self, make_message, fsm_context):
        from bot.handlers.admin.user_management_states import check_user_data

        msg = make_message(text="999888777", user_id=900003)

        await check_user_data(msg, fsm_context)

        msg.answer.assert_called_once()
        text = msg.answer.call_args[0][0]
        assert "unavailable" in text


class TestAssignRole:

    async def test_assign_role(self, make_callback_query, user_factory):
        from bot.handlers.admin.role_management_states import assign_role_confirm

        await user_factory(telegram_id=800010, role_id=1)
        admin_role = await get_role_id_by_name('ADMIN')

        call = make_callback_query(data=f"asr_{admin_role}_800010", user_id=900010)

        with patch('bot.handlers.admin.role_management_states.check_role_cached', new_callable=AsyncMock, return_value=1023):
            await assign_role_confirm(call)

        call.message.edit_text.assert_called_once()
        user = await check_user(800010)
        assert user['role_id'] == admin_role

    async def test_assign_user_role(self, make_callback_query, user_factory):
        from bot.handlers.admin.role_management_states import assign_role_confirm

        admin_role = await get_role_id_by_name('ADMIN')
        user_role = await get_role_id_by_name('USER')
        await user_factory(telegram_id=800011, role_id=admin_role)

        call = make_callback_query(data=f"asr_{user_role}_800011", user_id=900011)

        with patch('bot.handlers.admin.role_management_states.check_role_cached', new_callable=AsyncMock, return_value=127):
            await assign_role_confirm(call)

        call.message.edit_text.assert_called_once()
        user = await check_user(800011)
        assert user['role_id'] == user_role

    async def test_cannot_change_owner_role(self, make_callback_query, user_factory):
        from bot.handlers.admin.role_management_states import assign_role_confirm

        max_role = await select_max_role_id()
        await user_factory(telegram_id=800012, role_id=max_role)
        admin_role = await get_role_id_by_name('ADMIN')

        call = make_callback_query(data=f"asr_{admin_role}_800012", user_id=900012)

        with patch('bot.handlers.admin.role_management_states.check_role_cached', new_callable=AsyncMock, return_value=127):
            await assign_role_confirm(call)

        call.answer.assert_called_once()
        # Role should not change
        user = await check_user(800012)
        assert user['role_id'] == max_role


class TestReplenishBalance:

    async def test_replenish_user_balance(self, make_message, fsm_context, user_factory):
        from bot.handlers.admin.user_management_states import process_replenish_user_balance

        await user_factory(telegram_id=800020, balance=100)
        await fsm_context.update_data(target_user=800020)

        msg = make_message(text="500", user_id=900020)

        await process_replenish_user_balance(msg, fsm_context)

        msg.answer.assert_called_once()
        user = await check_user(800020)
        assert user['balance'] == Decimal("600")

    async def test_deduct_user_balance(self, make_message, fsm_context, user_factory):
        from bot.handlers.admin.user_management_states import process_deduct_user_balance

        await user_factory(telegram_id=800021, balance=500)
        await fsm_context.update_data(target_user=800021)

        msg = make_message(text="200", user_id=900021)

        await process_deduct_user_balance(msg, fsm_context)

        msg.answer.assert_called_once()
        user = await check_user(800021)
        assert user['balance'] == Decimal("300")

    async def test_deduct_insufficient_balance(self, make_message, fsm_context, user_factory):
        from bot.handlers.admin.user_management_states import process_deduct_user_balance

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
        from bot.handlers.admin.user_management_states import block_user_handler

        await user_factory(telegram_id=800030, role_id=1)

        call = make_callback_query(data="block-user_800030", user_id=900030)

        mock_auth = MagicMock()
        mock_auth.block_user = AsyncMock(return_value=True)

        with patch('bot.main.auth_middleware', mock_auth):
            await block_user_handler(call)

        call.message.edit_text.assert_called_once()
        mock_auth.block_user.assert_called_once_with(800030)

    async def test_unblock_user(self, make_callback_query, user_factory):
        from bot.handlers.admin.user_management_states import unblock_user_handler

        await user_factory(telegram_id=800031, role_id=1)

        call = make_callback_query(data="unblock-user_800031", user_id=900031)

        mock_auth = MagicMock()
        mock_auth.unblock_user = AsyncMock(return_value=True)

        with patch('bot.main.auth_middleware', mock_auth):
            await unblock_user_handler(call)

        call.message.edit_text.assert_called_once()
        mock_auth.unblock_user.assert_called_once_with(800031)

    async def test_cannot_block_owner(self, make_callback_query, user_factory):
        from bot.handlers.admin.user_management_states import block_user_handler

        max_role = await select_max_role_id()
        await user_factory(telegram_id=800032, role_id=max_role)

        call = make_callback_query(data="block-user_800032", user_id=900032)

        await block_user_handler(call)

        call.answer.assert_called_once()


class TestReplenishBalanceEdgeCases:

    async def test_replenish_non_numeric_input(self, make_message, fsm_context, user_factory):
        from bot.handlers.admin.user_management_states import process_replenish_user_balance

        await user_factory(telegram_id=800040, balance=100)
        await fsm_context.update_data(target_user=800040)

        msg = make_message(text="abc", user_id=900060)

        await process_replenish_user_balance(msg, fsm_context)

        msg.answer.assert_called_once()
        # Balance should not change
        user = await check_user(800040)
        assert user['balance'] == Decimal("100")

    async def test_replenish_negative_amount(self, make_message, fsm_context, user_factory):
        from bot.handlers.admin.user_management_states import process_replenish_user_balance

        await user_factory(telegram_id=800041, balance=100)
        await fsm_context.update_data(target_user=800041)

        msg = make_message(text="-500", user_id=900061)

        await process_replenish_user_balance(msg, fsm_context)

        msg.answer.assert_called_once()
        user = await check_user(800041)
        assert user['balance'] == Decimal("100")

    async def test_replenish_zero_amount(self, make_message, fsm_context, user_factory):
        from bot.handlers.admin.user_management_states import process_replenish_user_balance

        await user_factory(telegram_id=800042, balance=100)
        await fsm_context.update_data(target_user=800042)

        msg = make_message(text="0", user_id=900062)

        await process_replenish_user_balance(msg, fsm_context)

        msg.answer.assert_called_once()


class TestCategoryManagement:

    async def test_add_category(self, make_message, fsm_context):
        from bot.handlers.admin.categories_management_states import process_category_for_add

        msg = make_message(text="NewCategory", user_id=900040)

        await process_category_for_add(msg, fsm_context)

        msg.answer.assert_called_once()
        text = msg.answer.call_args[0][0]
        assert "success" in text

    async def test_add_duplicate_category(self, make_message, fsm_context, category_factory):
        from bot.handlers.admin.categories_management_states import process_category_for_add

        await category_factory("ExistingCat")

        msg = make_message(text="ExistingCat", user_id=900041)

        await process_category_for_add(msg, fsm_context)

        msg.answer.assert_called_once()
        text = msg.answer.call_args[0][0]
        assert "exist" in text

    async def test_delete_category(self, make_message, fsm_context, category_factory):
        from bot.handlers.admin.categories_management_states import process_category_for_delete

        await category_factory("ToDelete")

        msg = make_message(text="ToDelete", user_id=900042)

        await process_category_for_delete(msg, fsm_context)

        msg.answer.assert_called_once()
        text = msg.answer.call_args[0][0]
        assert "success" in text

    async def test_delete_nonexistent_category(self, make_message, fsm_context):
        from bot.handlers.admin.categories_management_states import process_category_for_delete

        msg = make_message(text="NoSuchCat", user_id=900043)

        await process_category_for_delete(msg, fsm_context)

        msg.answer.assert_called_once()
        text = msg.answer.call_args[0][0]
        assert "not_found" in text

    async def test_rename_category(self, make_message, fsm_context, category_factory):
        from bot.handlers.admin.categories_management_states import (
            check_category_for_update,
            check_category_name_for_update,
        )

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
        from bot.handlers.admin.goods_management_states import delete_str_item

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
        from bot.handlers.admin.goods_management_states import delete_str_item

        msg = make_message(text="NoSuchItem", user_id=900051)

        await delete_str_item(msg, fsm_context)

        msg.answer.assert_called_once()
        text = msg.answer.call_args[0][0]
        assert "not_found" in text

    async def test_show_items_not_found(self, make_message, fsm_context):
        from bot.handlers.admin.goods_management_states import show_str_item

        msg = make_message(text="NoItem", user_id=900052)

        await show_str_item(msg, fsm_context)

        msg.answer.assert_called_once()
        text = msg.answer.call_args[0][0]
        assert "not_found" in text
