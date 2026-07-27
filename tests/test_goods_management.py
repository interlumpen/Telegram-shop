from sqlalchemy import select

import pytest

from bot.database.main import Database
from bot.database.methods.read import get_item_info, select_item_values_amount
from bot.database.models.main import Goods, ItemValues
from bot.handlers.other import generate_short_hash
from bot.handlers.admin.goods_management import (
    goods_management_callback_handler, delete_item_callback_handler, delete_str_item,
    show_items_callback_handler, show_str_item, navigate_items_in_goods,
    item_info_callback_handler, process_delete_item_from_position,
)
from bot.states import GoodsFSM


async def _value_ids(item_name):
    """ItemValues ids belonging to a position, in insertion order."""
    async with Database().session() as s:
        item_id = (await s.execute(
            select(Goods.id).where(Goods.name == item_name)
        )).scalar()
        return list((await s.execute(
            select(ItemValues.id).where(ItemValues.item_id == item_id).order_by(ItemValues.id)
        )).scalars().all())


def _callbacks(mock_call_args):
    markup = mock_call_args[1]["reply_markup"]
    return [b.callback_data for row in markup.inline_keyboard for b in row]


class TestGoodsMenu:

    async def test_menu_lists_every_action(self, make_callback_query, fsm_context):
        call = make_callback_query(data="goods_management", user_id=900800)
        await fsm_context.set_state(GoodsFSM.waiting_item_name_delete)

        await goods_management_callback_handler(call, fsm_context)

        assert _callbacks(call.message.edit_text.call_args) == [
            "add_item", "update_item_amount", "update_item",
            "manage_sale", "delete_item", "show__items_in_position", "console",
        ]
        # Opening the menu drops any half-finished flow.
        assert await fsm_context.get_state() is None


class TestDeletePosition:

    async def test_prompt_sets_the_state(self, make_callback_query, fsm_context):
        call = make_callback_query(data="delete_item", user_id=900801)
        await delete_item_callback_handler(call, fsm_context)

        assert await fsm_context.get_state() == GoodsFSM.waiting_item_name_delete

    async def test_existing_position_is_deleted(self, make_message, fsm_context, item_factory):
        await item_factory(name="Doomed", price=100, values=[("v", False)])

        await delete_str_item(make_message(text="Doomed", user_id=1), fsm_context)

        assert await get_item_info("Doomed") is None
        assert await fsm_context.get_state() is None

    async def test_unknown_position_deletes_nothing(self, make_message, fsm_context, item_factory):
        await item_factory(name="Innocent", price=100, values=[("v", False)])

        await delete_str_item(make_message(text="NoSuchPosition", user_id=1), fsm_context)

        assert await get_item_info("Innocent") is not None


class TestShowItemsInPosition:

    async def test_prompt_sets_the_state(self, make_callback_query, fsm_context):
        call = make_callback_query(data="show__items_in_position", user_id=900810)
        await show_items_callback_handler(call, fsm_context)

        assert await fsm_context.get_state() == GoodsFSM.waiting_item_name_show

    async def test_listing_stores_the_hash_mapping(self, make_message, fsm_context, item_factory):
        await item_factory(name="Stocked", price=100, values=[("a", False), ("b", False)])
        msg = make_message(text="Stocked", user_id=1)

        await show_str_item(msg, fsm_context)

        data = await fsm_context.get_data()
        item_hash = generate_short_hash("Stocked")
        assert data["item_hash_mapping"] == {item_hash: "Stocked"}
        assert data["current_position_name"] == "Stocked"
        # Every row is addressable and fits Telegram's 64-byte callback cap.
        cbs = _callbacks(msg.answer.call_args)
        assert any(c.startswith("si_") for c in cbs)
        assert all(len(c.encode("utf-8")) <= 64 for c in cbs)

    async def test_unknown_position_clears_the_state(self, make_message, fsm_context):
        await fsm_context.set_state(GoodsFSM.waiting_item_name_show)
        await show_str_item(make_message(text="Ghost", user_id=1), fsm_context)

        assert await fsm_context.get_state() is None

    async def test_position_without_stock_reports_empty(self, make_message, fsm_context,
                                                        item_factory):
        await item_factory(name="SoldOut", price=100, values=[])
        msg = make_message(text="SoldOut", user_id=1)

        await show_str_item(msg, fsm_context)

        assert _callbacks(msg.answer.call_args) == ["goods_management"]
        assert await fsm_context.get_state() is None


class TestNavigateItemsInPosition:

    async def test_paging_resolves_the_position_from_the_hash(self, make_message,
                                                              make_callback_query, fsm_context,
                                                              item_factory):
        await item_factory(name="Paged", price=100, values=[("a", False), ("b", False)])
        await show_str_item(make_message(text="Paged", user_id=1), fsm_context)
        item_hash = generate_short_hash("Paged")

        call = make_callback_query(data=f"gip_{item_hash}_0", user_id=1)
        await navigate_items_in_goods(call, fsm_context)

        assert any(c.startswith("si_") for c in _callbacks(call.message.edit_text.call_args))

    async def test_unknown_hash_falls_back_to_the_remembered_position(self, make_message,
                                                                      make_callback_query,
                                                                      fsm_context, item_factory):
        await item_factory(name="Remembered", price=100, values=[("a", False)])
        await show_str_item(make_message(text="Remembered", user_id=1), fsm_context)

        call = make_callback_query(data="gip_deadbeef_0", user_id=1)
        await navigate_items_in_goods(call, fsm_context)

        call.message.edit_text.assert_called_once()

    async def test_no_hash_and_no_memory_is_rejected(self, make_callback_query, fsm_context):
        call = make_callback_query(data="gip_deadbeef_0", user_id=1)
        await navigate_items_in_goods(call, fsm_context)

        call.answer.assert_called_once()
        call.message.edit_text.assert_not_called()

    async def test_malformed_page_defaults_to_the_first(self, make_message, make_callback_query,
                                                        fsm_context, item_factory):
        await item_factory(name="BadPage", price=100, values=[("a", False)])
        await show_str_item(make_message(text="BadPage", user_id=1), fsm_context)

        # No trailing page number at all — must not raise.
        call = make_callback_query(data="gip_notanumber", user_id=1)
        await navigate_items_in_goods(call, fsm_context)

        assert call.message.edit_text.called or call.answer.called

    async def test_emptied_position_reports_empty_on_paging(self, make_message,
                                                            make_callback_query, fsm_context,
                                                            item_factory):
        await item_factory(name="Vanishing", price=100, values=[("a", False)])
        await show_str_item(make_message(text="Vanishing", user_id=1), fsm_context)
        item_hash = generate_short_hash("Vanishing")

        from sqlalchemy import delete as sa_delete, select as sa_select
        from bot.database.main import Database
        from bot.database.models.main import Goods, ItemValues
        async with Database().session() as s:
            item_id = (await s.execute(sa_select(Goods.id).where(Goods.name == "Vanishing"))).scalar()
            await s.execute(sa_delete(ItemValues).where(ItemValues.item_id == item_id))

        call = make_callback_query(data=f"gip_{item_hash}_0", user_id=1)
        await navigate_items_in_goods(call, fsm_context)

        assert _callbacks(call.message.edit_text.call_args) == ["goods_management"]


class TestItemInfo:

    async def test_detail_view_offers_delete_and_back(self, make_message, make_callback_query,
                                                      fsm_context, item_factory):
        await item_factory(name="Detailed", price=250, values=[("secret-key", False)])
        await show_str_item(make_message(text="Detailed", user_id=1), fsm_context)

        value_id = (await _value_ids("Detailed"))[0]
        item_hash = generate_short_hash("Detailed")

        call = make_callback_query(data=f"si_{value_id}_{item_hash}_0", user_id=1)
        await item_info_callback_handler(call, fsm_context)

        assert _callbacks(call.message.edit_text.call_args) == [
            f"dip_{value_id}", f"gip_{item_hash}_0",
        ]
        text = call.message.edit_text.call_args[0][0]
        assert "secret-key" in text   # the admin is shown the delivered value
        assert "250" in text
        # State carries what the delete handler needs.
        data = await fsm_context.get_data()
        assert data["delete_item_id"] == value_id
        assert data["delete_item_name"] == "Detailed"

    @pytest.mark.parametrize("payload,expected_answer", [
        ("si_x", True),          # too few segments
        ("si_abc_hash_0", True),  # non-numeric id
        ("si_999999_hash_0", True),  # id that does not exist
    ])
    async def test_bad_payloads_answer_instead_of_rendering(self, make_callback_query, fsm_context,
                                                            payload, expected_answer):
        call = make_callback_query(data=payload, user_id=1)
        await item_info_callback_handler(call, fsm_context)

        assert call.answer.called is expected_answer
        call.message.edit_text.assert_not_called()


class TestDeleteItemFromPosition:

    async def test_value_is_removed_and_the_list_redrawn(self, make_message, make_callback_query,
                                                         fsm_context, item_factory):
        await item_factory(name="Trimmed", price=100,
                           values=[("a", False), ("b", False), ("c", False)])
        await show_str_item(make_message(text="Trimmed", user_id=1), fsm_context)

        value_id = (await _value_ids("Trimmed"))[0]
        item_hash = generate_short_hash("Trimmed")
        info = make_callback_query(data=f"si_{value_id}_{item_hash}_0", user_id=1)
        await item_info_callback_handler(info, fsm_context)

        call = make_callback_query(data=f"dip_{value_id}", user_id=1)
        await process_delete_item_from_position(call, fsm_context)

        assert await select_item_values_amount("Trimmed") == 2
        # The refreshed list is rendered, not just a bare confirmation.
        assert any(c.startswith("si_") for c in _callbacks(call.message.edit_text.call_args))

    async def test_deleting_the_last_value_reports_an_empty_position(self, make_message,
                                                                     make_callback_query,
                                                                     fsm_context, item_factory):
        await item_factory(name="LastOne", price=100, values=[("only", False)])
        await show_str_item(make_message(text="LastOne", user_id=1), fsm_context)

        value_id = (await _value_ids("LastOne"))[0]
        item_hash = generate_short_hash("LastOne")
        info = make_callback_query(data=f"si_{value_id}_{item_hash}_0", user_id=1)
        await item_info_callback_handler(info, fsm_context)

        call = make_callback_query(data=f"dip_{value_id}", user_id=1)
        await process_delete_item_from_position(call, fsm_context)

        assert await select_item_values_amount("LastOne") == 0
        assert _callbacks(call.message.edit_text.call_args) == ["goods_management"]
        # The position itself survives — only its stock is gone.
        assert await get_item_info("LastOne") is not None

    async def test_malformed_id_deletes_nothing(self, make_callback_query, fsm_context,
                                                item_factory):
        await item_factory(name="Untouched", price=100, values=[("v", False)])

        call = make_callback_query(data="dip_notanumber", user_id=1)
        await process_delete_item_from_position(call, fsm_context)

        call.answer.assert_called_once()
        assert await select_item_values_amount("Untouched") == 1

    async def test_already_deleted_value_is_reported(self, make_callback_query, fsm_context):
        call = make_callback_query(data="dip_999999", user_id=1)
        await process_delete_item_from_position(call, fsm_context)

        call.answer.assert_called_once()
        call.message.edit_text.assert_called_once()

    async def test_deleting_without_list_context_still_works(self, make_callback_query,
                                                             fsm_context, item_factory):
        """Reached from a stale card: no hash in state, so just confirm."""
        await item_factory(name="NoContext", price=100, values=[("v", False)])
        value_id = (await _value_ids("NoContext"))[0]

        call = make_callback_query(data=f"dip_{value_id}", user_id=1)
        await process_delete_item_from_position(call, fsm_context)

        assert await select_item_values_amount("NoContext") == 0
        assert _callbacks(call.message.edit_text.call_args) == ["goods_management"]
