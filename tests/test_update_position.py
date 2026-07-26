from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from bot.database.methods.read import (
    get_item_info, select_item_values_amount, check_value,
)
from bot.handlers.admin.update_position import (
    _show_update_item_error, _UPDATE_ITEM_ERRORS,
    update_item_amount_callback_handler, check_item_name_for_amount_upd,
    updating_item_values, updating_item_amount,
    update_item_callback_handler, check_item_name_for_update, update_item_name,
    update_item_description, update_item_price, update_item_process,
    update_item_infinity, updating_item, update_item_no_infinity,
)
from bot.states import UpdateItemFSM


async def _walk_to_infinity_question(make_message, fsm_context, *,
                                     old_name, new_name, price="200"):
    """Drive the edit branch from the name prompt to the infinity question."""
    await check_item_name_for_update(make_message(text=old_name, user_id=1), fsm_context)
    await update_item_name(make_message(text=new_name, user_id=1), fsm_context)
    await update_item_description(make_message(text="New description", user_id=1), fsm_context)
    await update_item_price(make_message(text=price, user_id=1), fsm_context)


class TestUpdateItemErrorMapping:

    @pytest.mark.parametrize("code,expected_key", [
        ("position_invalid", "admin.goods.update.position.invalid"),
        ("position_exists", "admin.goods.update.position.exists"),
        ("db_error", "errors.something_wrong"),
        ("something_unmapped", "errors.something_wrong"),  # unknown codes fall back
        (None, "errors.something_wrong"),
    ])
    async def test_every_code_maps_to_a_message(self, code, expected_key):
        send = AsyncMock()
        with patch('bot.handlers.admin.update_position.localize',
                   side_effect=lambda key, **kw: key):
            await _show_update_item_error(send, code)
        assert send.await_args[0][0] == expected_key

    def test_mapping_covers_the_documented_codes(self):
        assert set(_UPDATE_ITEM_ERRORS) == {"position_invalid", "position_exists", "db_error"}


# --- Branch 1: adding stock to an existing position ---

class TestRestockBranch:

    async def test_start_sets_the_name_state(self, make_callback_query, fsm_context):
        call = make_callback_query(data="update_item_amount", user_id=900700)
        await update_item_amount_callback_handler(call, fsm_context)

        assert await fsm_context.get_state() == UpdateItemFSM.waiting_item_name_for_amount_upd

    async def test_known_finite_item_advances(self, make_message, fsm_context, item_factory):
        await item_factory(name="Restockable", price=100, values=[("v1", False)])

        await check_item_name_for_amount_upd(
            make_message(text="Restockable", user_id=1), fsm_context
        )

        assert await fsm_context.get_state() == UpdateItemFSM.waiting_item_values_upd
        assert (await fsm_context.get_data())["item_name"] == "Restockable"

    async def test_unknown_item_keeps_the_state(self, make_message, fsm_context):
        await fsm_context.set_state(UpdateItemFSM.waiting_item_name_for_amount_upd)
        await check_item_name_for_amount_upd(make_message(text="Ghost", user_id=1), fsm_context)

        assert await fsm_context.get_state() == UpdateItemFSM.waiting_item_name_for_amount_upd
        assert "item_name" not in await fsm_context.get_data()

    async def test_infinite_item_cannot_take_individual_values(self, make_message, fsm_context,
                                                               item_factory):
        """An unlimited position has no per-unit stock to append to."""
        await item_factory(name="Unlimited", price=100, values=[("forever", True)])

        await fsm_context.set_state(UpdateItemFSM.waiting_item_name_for_amount_upd)
        await check_item_name_for_amount_upd(make_message(text="Unlimited", user_id=1), fsm_context)

        assert await fsm_context.get_state() == UpdateItemFSM.waiting_item_name_for_amount_upd
        assert "item_name" not in await fsm_context.get_data()

    async def test_collected_values_are_appended_to_stock(self, make_message, make_callback_query,
                                                          fsm_context, item_factory):
        await item_factory(name="GrowingItem", price=100, values=[("old", False)])

        await check_item_name_for_amount_upd(
            make_message(text="GrowingItem", user_id=1), fsm_context
        )
        for v in ("new1", "new2"):
            await updating_item_values(make_message(text=v, user_id=1), fsm_context)

        call = make_callback_query(data="finish_updating_items", user_id=1)
        with patch('bot.handlers.admin.update_position._parse_channel_username', return_value=None):
            await updating_item_amount(call, fsm_context)

        assert await select_item_values_amount("GrowingItem") == 3  # old + new1 + new2
        assert await fsm_context.get_state() is None

    async def test_duplicates_and_blanks_are_skipped(self, make_message, make_callback_query,
                                                     fsm_context, item_factory):
        await item_factory(name="DupRestock", price=100, values=[("existing", False)])

        await check_item_name_for_amount_upd(
            make_message(text="DupRestock", user_id=1), fsm_context
        )
        # "existing" already lives in the DB, "dup" repeats inside the batch.
        for v in ("existing", "dup", "dup", "", "   ", "fresh"):
            await updating_item_values(make_message(text=v, user_id=1), fsm_context)

        call = make_callback_query(data="finish_updating_items", user_id=1)
        with patch('bot.handlers.admin.update_position._parse_channel_username', return_value=None):
            await updating_item_amount(call, fsm_context)

        # existing + dup + fresh
        assert await select_item_values_amount("DupRestock") == 3

    async def test_restock_subscribers_are_notified(self, make_message, make_callback_query,
                                                    fsm_context, item_factory):
        await item_factory(name="WaitedOn", price=100, values=[("v", False)])

        await check_item_name_for_amount_upd(make_message(text="WaitedOn", user_id=1), fsm_context)
        await updating_item_values(make_message(text="restocked", user_id=1), fsm_context)

        call = make_callback_query(data="finish_updating_items", user_id=1)
        with patch('bot.handlers.admin.update_position._parse_channel_username', return_value=None), \
                patch('bot.handlers.admin.update_position._notify_restock_safe',
                      new_callable=AsyncMock) as notify:
            await updating_item_amount(call, fsm_context)

        notify.assert_awaited_once()
        assert notify.await_args[0][1] == "WaitedOn"


# --- Branch 2: editing name / description / price / stock mode ---

class TestEditBranchNavigation:

    async def test_start_sets_the_name_state(self, make_callback_query, fsm_context):
        call = make_callback_query(data="update_item", user_id=900710)
        await update_item_callback_handler(call, fsm_context)

        assert await fsm_context.get_state() == UpdateItemFSM.waiting_item_name_for_update

    async def test_known_item_captures_its_category(self, make_message, fsm_context, item_factory):
        await item_factory(name="Editable", price=100, category="EditCat", values=[("v", False)])

        await check_item_name_for_update(make_message(text="Editable", user_id=1), fsm_context)

        data = await fsm_context.get_data()
        assert data["item_old_name"] == "Editable"
        assert data["item_category"] == "EditCat"
        assert await fsm_context.get_state() == UpdateItemFSM.waiting_item_new_name

    async def test_unknown_item_keeps_the_state(self, make_message, fsm_context):
        await fsm_context.set_state(UpdateItemFSM.waiting_item_name_for_update)
        await check_item_name_for_update(make_message(text="Ghost", user_id=1), fsm_context)

        assert await fsm_context.get_state() == UpdateItemFSM.waiting_item_name_for_update

    @pytest.mark.parametrize("bad_name", ["", "   ", "A" * 101, "bad\x00name"])
    async def test_unsafe_new_name_keeps_the_state(self, make_message, fsm_context, bad_name):
        await fsm_context.set_state(UpdateItemFSM.waiting_item_new_name)
        await update_item_name(make_message(text=bad_name, user_id=1), fsm_context)

        assert await fsm_context.get_state() == UpdateItemFSM.waiting_item_new_name
        assert "item_new_name" not in await fsm_context.get_data()

    @pytest.mark.parametrize("bad_price", ["abc", "", "0", "-5", "12.50"])
    async def test_invalid_price_keeps_the_state(self, make_message, fsm_context,
                                                 item_factory, bad_price):
        await item_factory(name="PriceItem", price=100, values=[("v", False)])
        await check_item_name_for_update(make_message(text="PriceItem", user_id=1), fsm_context)
        await update_item_name(make_message(text="PriceItem", user_id=1), fsm_context)
        await update_item_description(make_message(text="d", user_id=1), fsm_context)
        await fsm_context.set_state(UpdateItemFSM.waiting_item_price)

        await update_item_price(make_message(text=bad_price, user_id=1), fsm_context)

        assert await fsm_context.get_state() == UpdateItemFSM.waiting_item_price

    async def test_finite_item_is_offered_the_make_infinite_question(self, make_message,
                                                                     fsm_context, item_factory):
        await item_factory(name="FiniteOne", price=100, values=[("v", False)])
        msg = make_message(text="200", user_id=1)

        await check_item_name_for_update(make_message(text="FiniteOne", user_id=1), fsm_context)
        await update_item_name(make_message(text="FiniteOne", user_id=1), fsm_context)
        await update_item_description(make_message(text="d", user_id=1), fsm_context)
        await update_item_price(msg, fsm_context)

        cbs = [
            b.callback_data
            for row in msg.answer.call_args[1]["reply_markup"].inline_keyboard for b in row
        ]
        assert "change_make_infinity_yes" in cbs
        assert await fsm_context.get_state() == UpdateItemFSM.waiting_make_infinity

    async def test_infinite_item_is_offered_the_deny_question(self, make_message,
                                                              fsm_context, item_factory):
        await item_factory(name="InfiniteOne", price=100, values=[("forever", True)])
        msg = make_message(text="200", user_id=1)

        await check_item_name_for_update(make_message(text="InfiniteOne", user_id=1), fsm_context)
        await update_item_name(make_message(text="InfiniteOne", user_id=1), fsm_context)
        await update_item_description(make_message(text="d", user_id=1), fsm_context)
        await update_item_price(msg, fsm_context)

        cbs = [
            b.callback_data
            for row in msg.answer.call_args[1]["reply_markup"].inline_keyboard for b in row
        ]
        assert "change_deny_infinity_yes" in cbs


class TestMetadataOnlyUpdate:

    async def test_no_answer_updates_meta_and_keeps_stock(self, make_message, make_callback_query,
                                                          fsm_context, item_factory):
        await item_factory(name="MetaOnly", price=100, category="MetaCat",
                           values=[("keep-me", False)])
        await _walk_to_infinity_question(
            make_message, fsm_context, old_name="MetaOnly", new_name="MetaRenamed"
        )

        call = make_callback_query(data="change_make_infinity_no", user_id=1)
        await update_item_process(call, fsm_context)

        assert await get_item_info("MetaOnly") is None
        item = await get_item_info("MetaRenamed")
        assert item["price"] == Decimal("200")
        assert item["description"] == "New description"
        # Stock survives a metadata-only edit.
        assert await select_item_values_amount("MetaRenamed") == 1
        assert await fsm_context.get_state() is None

    async def test_rename_onto_an_existing_name_is_rejected(self, make_message, make_callback_query,
                                                            fsm_context, item_factory):
        await item_factory(name="Source", price=100, category="ClashCat", values=[("s", False)])
        await item_factory(name="Taken", price=100, category="ClashCat", values=[("t", False)])

        await _walk_to_infinity_question(
            make_message, fsm_context, old_name="Source", new_name="Taken"
        )
        call = make_callback_query(data="change_make_infinity_no", user_id=1)
        await update_item_process(call, fsm_context)

        # Neither position was harmed by the rejected rename.
        assert await get_item_info("Source") is not None
        assert await select_item_values_amount("Source") == 1
        assert await select_item_values_amount("Taken") == 1
        assert await fsm_context.get_state() is None


class TestSwitchToInfinite:

    async def test_yes_asks_for_a_single_value(self, make_message, make_callback_query,
                                               fsm_context, item_factory):
        await item_factory(name="ToInfinite", price=100, values=[("a", False)])
        await _walk_to_infinity_question(
            make_message, fsm_context, old_name="ToInfinite", new_name="ToInfinite"
        )

        await update_item_process(
            make_callback_query(data="change_make_infinity_yes", user_id=1), fsm_context
        )

        assert await fsm_context.get_state() == UpdateItemFSM.waiting_single_value

    async def test_stock_is_replaced_by_one_infinite_value(self, make_message, make_callback_query,
                                                           fsm_context, item_factory):
        await item_factory(name="BecomesInfinite", price=100, values=[("a", False), ("b", False)])
        await _walk_to_infinity_question(
            make_message, fsm_context, old_name="BecomesInfinite", new_name="BecomesInfinite"
        )
        await update_item_process(
            make_callback_query(data="change_make_infinity_yes", user_id=1), fsm_context
        )

        await update_item_infinity(make_message(text="forever-key", user_id=1), fsm_context)

        assert await check_value("BecomesInfinite") is True
        assert await select_item_values_amount("BecomesInfinite") == 1
        assert await fsm_context.get_state() is None

    async def test_blank_value_changes_nothing(self, make_message, make_callback_query,
                                               fsm_context, item_factory):
        await item_factory(name="StaysFinite", price=100, values=[("a", False), ("b", False)])
        await _walk_to_infinity_question(
            make_message, fsm_context, old_name="StaysFinite", new_name="StaysFinite"
        )
        await update_item_process(
            make_callback_query(data="change_make_infinity_yes", user_id=1), fsm_context
        )

        await update_item_infinity(make_message(text="   ", user_id=1), fsm_context)

        assert await check_value("StaysFinite") is False
        assert await select_item_values_amount("StaysFinite") == 2
        assert await fsm_context.get_state() == UpdateItemFSM.waiting_single_value

    async def test_rejected_rename_leaves_the_old_stock_intact(self, make_message,
                                                               make_callback_query, fsm_context,
                                                               item_factory):
        """The stock swap and the rename share one transaction."""
        await item_factory(name="Keeper", price=100, category="AtomCat", values=[("a", False),
                                                                                 ("b", False)])
        await item_factory(name="Occupied", price=100, category="AtomCat", values=[("x", False)])

        await _walk_to_infinity_question(
            make_message, fsm_context, old_name="Keeper", new_name="Occupied"
        )
        await update_item_process(
            make_callback_query(data="change_make_infinity_yes", user_id=1), fsm_context
        )
        await update_item_infinity(make_message(text="new-forever", user_id=1), fsm_context)

        assert await select_item_values_amount("Keeper") == 2
        assert await check_value("Keeper") is False
        assert await select_item_values_amount("Occupied") == 1


class TestSwitchToFinite:

    async def test_yes_collects_multiple_values(self, make_message, make_callback_query,
                                                fsm_context, item_factory):
        await item_factory(name="ToFinite", price=100, values=[("forever", True)])
        await _walk_to_infinity_question(
            make_message, fsm_context, old_name="ToFinite", new_name="ToFinite"
        )

        await update_item_process(
            make_callback_query(data="change_deny_infinity_yes", user_id=1), fsm_context
        )

        assert await fsm_context.get_state() == UpdateItemFSM.waiting_multiple_values

    async def test_collected_values_replace_the_infinite_one(self, make_message,
                                                             make_callback_query, fsm_context,
                                                             item_factory):
        await item_factory(name="BecomesFinite", price=100, values=[("forever", True)])
        await _walk_to_infinity_question(
            make_message, fsm_context, old_name="BecomesFinite", new_name="BecomesFinite"
        )
        await update_item_process(
            make_callback_query(data="change_deny_infinity_yes", user_id=1), fsm_context
        )
        for v in ("k1", "k2", "k3"):
            await updating_item(make_message(text=v, user_id=1), fsm_context)

        call = make_callback_query(data="finish_update_item", user_id=1)
        with patch('bot.handlers.admin.update_position._parse_channel_username', return_value=None):
            await update_item_no_infinity(call, fsm_context)

        assert await check_value("BecomesFinite") is False
        assert await select_item_values_amount("BecomesFinite") == 3
        assert await fsm_context.get_state() is None

    async def test_duplicates_and_blanks_are_dropped(self, make_message, make_callback_query,
                                                     fsm_context, item_factory):
        await item_factory(name="DedupedSwitch", price=100, values=[("forever", True)])
        await _walk_to_infinity_question(
            make_message, fsm_context, old_name="DedupedSwitch", new_name="DedupedSwitch"
        )
        await update_item_process(
            make_callback_query(data="change_deny_infinity_yes", user_id=1), fsm_context
        )
        for v in ("k1", "k1", "", "  ", "k2"):
            await updating_item(make_message(text=v, user_id=1), fsm_context)

        call = make_callback_query(data="finish_update_item", user_id=1)
        with patch('bot.handlers.admin.update_position._parse_channel_username', return_value=None):
            await update_item_no_infinity(call, fsm_context)

        assert await select_item_values_amount("DedupedSwitch") == 2

    async def test_rejected_rename_leaves_the_infinite_stock_intact(self, make_message,
                                                                    make_callback_query,
                                                                    fsm_context, item_factory):
        await item_factory(name="StillInfinite", price=100, category="AtomCat2",
                           values=[("forever", True)])
        await item_factory(name="NameTaken", price=100, category="AtomCat2", values=[("x", False)])

        await _walk_to_infinity_question(
            make_message, fsm_context, old_name="StillInfinite", new_name="NameTaken"
        )
        await update_item_process(
            make_callback_query(data="change_deny_infinity_yes", user_id=1), fsm_context
        )
        await updating_item(make_message(text="k1", user_id=1), fsm_context)

        call = make_callback_query(data="finish_update_item", user_id=1)
        with patch('bot.handlers.admin.update_position._parse_channel_username', return_value=None):
            await update_item_no_infinity(call, fsm_context)

        assert await check_value("StillInfinite") is True
        assert await select_item_values_amount("StillInfinite") == 1
        assert await select_item_values_amount("NameTaken") == 1

    async def test_channel_announcement_is_sent_when_configured(self, make_message,
                                                               make_callback_query, fsm_context,
                                                               item_factory):
        await item_factory(name="Announced", price=100, values=[("forever", True)])
        await _walk_to_infinity_question(
            make_message, fsm_context, old_name="Announced", new_name="Announced"
        )
        await update_item_process(
            make_callback_query(data="change_deny_infinity_yes", user_id=1), fsm_context
        )
        await updating_item(make_message(text="k1", user_id=1), fsm_context)

        call = make_callback_query(data="finish_update_item", user_id=1)
        with patch('bot.handlers.admin.update_position._parse_channel_username',
                   return_value="myshop"):
            await update_item_no_infinity(call, fsm_context)

        call.bot.send_message.assert_awaited_once()
        assert "Announced" in call.bot.send_message.await_args[1]["text"]
