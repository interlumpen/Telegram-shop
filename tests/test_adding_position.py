from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from bot.database.methods.read import (
    get_item_info, select_item_values_amount, check_value,
)
from bot.handlers.admin.adding_position import (
    add_item_callback_handler, check_item_name_for_add, add_item_description,
    add_item_price, check_category_for_add_item, adding_value_to_position,
    collect_item_value, finish_adding_items_callback_handler,
    finish_adding_item_callback_handler,
)
from bot.states import AddItemFSM


async def _walk_to_infinity_question(make_message, fsm_context, *,
                                     name="NewItem", price="100", category="AddCat"):
    """Drive the FSM from the name prompt up to the infinite-stock question."""
    await check_item_name_for_add(make_message(text=name, user_id=1), fsm_context)
    await add_item_description(make_message(text="A description", user_id=1), fsm_context)
    await add_item_price(make_message(text=price, user_id=1), fsm_context)
    await check_category_for_add_item(make_message(text=category, user_id=1), fsm_context)


class TestAddItemStart:

    async def test_start_sets_the_name_state(self, make_callback_query, fsm_context):
        call = make_callback_query(data="add_item", user_id=900600)
        await add_item_callback_handler(call, fsm_context)

        assert await fsm_context.get_state() == AddItemFSM.waiting_item_name
        call.message.edit_text.assert_called_once()


class TestItemNameStep:

    async def test_valid_name_advances_to_description(self, make_message, fsm_context):
        await check_item_name_for_add(make_message(text="Fresh Item", user_id=1), fsm_context)

        assert await fsm_context.get_state() == AddItemFSM.waiting_item_description
        assert (await fsm_context.get_data())["item_name"] == "Fresh Item"

    async def test_existing_name_is_refused(self, make_message, fsm_context, item_factory):
        await item_factory(name="AlreadyHere", price=10, category="C", values=[("v", False)])

        await fsm_context.set_state(AddItemFSM.waiting_item_name)
        await check_item_name_for_add(make_message(text="AlreadyHere", user_id=1), fsm_context)

        assert await fsm_context.get_state() == AddItemFSM.waiting_item_name

    @pytest.mark.parametrize("bad_name", [
        "",
        "   ",
        "A" * 101,          # over the 100-char cap
        "bad\x00name",      # control characters
    ])
    async def test_unsafe_name_is_refused(self, make_message, fsm_context, bad_name):
        await fsm_context.set_state(AddItemFSM.waiting_item_name)
        await check_item_name_for_add(make_message(text=bad_name, user_id=1), fsm_context)

        assert await fsm_context.get_state() == AddItemFSM.waiting_item_name
        assert "item_name" not in await fsm_context.get_data()


class TestPriceStep:

    @pytest.mark.parametrize("text,expected", [
        ("100", 100),
        ("1", 1),                  # the minimum accepted price
        ("99999999", 99_999_999),  # Numeric(12, 2) leaves 10 integer digits
    ])
    async def test_valid_price_advances_to_category(self, make_message, fsm_context,
                                                    text, expected):
        await add_item_price(make_message(text=text, user_id=1), fsm_context)

        assert await fsm_context.get_state() == AddItemFSM.waiting_category
        assert (await fsm_context.get_data())["item_price"] == expected

    @pytest.mark.parametrize("bad_price", [
        "abc", "", "-10", "0",
        "99.99",       # prices are whole units only
        "100000000",   # one over the cap the DB column can hold
        "１００",       # non-ASCII digits are not accepted
    ])
    async def test_invalid_price_keeps_the_state(self, make_message, fsm_context, bad_price):
        await fsm_context.set_state(AddItemFSM.waiting_item_price)
        await add_item_price(make_message(text=bad_price, user_id=1), fsm_context)

        assert await fsm_context.get_state() == AddItemFSM.waiting_item_price
        assert "item_price" not in await fsm_context.get_data()


class TestCategoryStep:

    async def test_existing_category_advances(self, make_message, fsm_context, category_factory):
        await category_factory("RealCat")

        await check_category_for_add_item(make_message(text="RealCat", user_id=1), fsm_context)

        assert await fsm_context.get_state() == AddItemFSM.waiting_infinity
        assert (await fsm_context.get_data())["item_category"] == "RealCat"

    async def test_unknown_category_keeps_the_state(self, make_message, fsm_context):
        await fsm_context.set_state(AddItemFSM.waiting_category)
        await check_category_for_add_item(make_message(text="Ghost", user_id=1), fsm_context)

        assert await fsm_context.get_state() == AddItemFSM.waiting_category
        assert "item_category" not in await fsm_context.get_data()


class TestInfinityBranch:

    @pytest.mark.parametrize("answer,expected_state,expected_flag", [
        ("no", AddItemFSM.waiting_values, False),
        ("yes", AddItemFSM.waiting_single_value, True),
    ])
    async def test_branch(self, make_callback_query, fsm_context,
                          answer, expected_state, expected_flag):
        call = make_callback_query(data=f"infinity_{answer}", user_id=1)
        await adding_value_to_position(call, fsm_context)

        assert await fsm_context.get_state() == expected_state
        assert (await fsm_context.get_data())["is_infinity"] is expected_flag


class TestCollectValues:

    async def test_values_accumulate_in_state(self, make_message, fsm_context):
        for v in ("key-1", "key-2", "key-3"):
            await collect_item_value(make_message(text=v, user_id=1), fsm_context)

        assert (await fsm_context.get_data())["item_values"] == ["key-1", "key-2", "key-3"]

    async def test_finish_button_appears_with_the_first_value(self, make_message, fsm_context):
        msg = make_message(text="key-1", user_id=1)
        await collect_item_value(msg, fsm_context)

        markup = msg.answer.call_args[1]["reply_markup"]
        cbs = [b.callback_data for row in markup.inline_keyboard for b in row]
        assert cbs == ["finish_adding_items", "goods_management"]


class TestFinishMultiValue:

    async def test_creates_the_item_with_all_values(self, make_message, make_callback_query,
                                                    fsm_context, category_factory):
        await category_factory("AddCat")
        await _walk_to_infinity_question(make_message, fsm_context, name="MultiItem")
        await adding_value_to_position(
            make_callback_query(data="infinity_no", user_id=1), fsm_context
        )
        for v in ("k1", "k2"):
            await collect_item_value(make_message(text=v, user_id=1), fsm_context)

        call = make_callback_query(data="finish_adding_items", user_id=1)
        with patch('bot.handlers.admin.adding_position._parse_channel_username', return_value=None):
            await finish_adding_items_callback_handler(call, fsm_context)

        item = await get_item_info("MultiItem")
        assert item is not None
        assert item["price"] == Decimal("100")
        assert item["description"] == "A description"
        assert await select_item_values_amount("MultiItem") == 2
        assert await check_value("MultiItem") is False   # finite stock
        assert await fsm_context.get_state() is None

    async def test_duplicate_and_blank_values_are_skipped(self, make_message, make_callback_query,
                                                          fsm_context, category_factory):
        await category_factory("AddCat")
        await _walk_to_infinity_question(make_message, fsm_context, name="DupItem")
        await adding_value_to_position(
            make_callback_query(data="infinity_no", user_id=1), fsm_context
        )
        # k1 twice (batch dup), one blank, one whitespace-only.
        for v in ("k1", "k1", "", "   ", "k2"):
            await collect_item_value(make_message(text=v, user_id=1), fsm_context)

        call = make_callback_query(data="finish_adding_items", user_id=1)
        with patch('bot.handlers.admin.adding_position._parse_channel_username', return_value=None):
            await finish_adding_items_callback_handler(call, fsm_context)

        assert await select_item_values_amount("DupItem") == 2  # only k1 and k2

    async def test_restock_subscribers_are_notified(self, make_message, make_callback_query,
                                                    fsm_context, category_factory,
                                                    user_factory, item_factory):
        """A position added back in stock must wake its waiting list."""
        await category_factory("AddCat")
        await _walk_to_infinity_question(make_message, fsm_context, name="AwaitedItem")
        await adding_value_to_position(
            make_callback_query(data="infinity_no", user_id=1), fsm_context
        )
        await collect_item_value(make_message(text="k1", user_id=1), fsm_context)

        call = make_callback_query(data="finish_adding_items", user_id=1)
        with patch('bot.handlers.admin.adding_position._parse_channel_username', return_value=None), \
                patch('bot.handlers.admin.adding_position._notify_restock_safe',
                      new_callable=AsyncMock) as notify:
            await finish_adding_items_callback_handler(call, fsm_context)

        notify.assert_awaited_once()
        assert notify.await_args[0][1] == "AwaitedItem"

    async def test_channel_announcement_is_sent_when_configured(self, make_message,
                                                                make_callback_query, fsm_context,
                                                                category_factory):
        await category_factory("AddCat")
        await _walk_to_infinity_question(make_message, fsm_context, name="AnnouncedItem")
        await adding_value_to_position(
            make_callback_query(data="infinity_no", user_id=1), fsm_context
        )
        await collect_item_value(make_message(text="k1", user_id=1), fsm_context)

        call = make_callback_query(data="finish_adding_items", user_id=1)
        with patch('bot.handlers.admin.adding_position._parse_channel_username',
                   return_value="myshop"):
            await finish_adding_items_callback_handler(call, fsm_context)

        call.bot.send_message.assert_awaited_once()
        assert "AnnouncedItem" in call.bot.send_message.await_args[1]["text"]

    async def test_a_blocked_channel_does_not_break_the_upload(self, make_message,
                                                               make_callback_query, fsm_context,
                                                               category_factory):
        from aiogram.exceptions import TelegramForbiddenError
        from unittest.mock import MagicMock

        await category_factory("AddCat")
        await _walk_to_infinity_question(make_message, fsm_context, name="BlockedChannelItem")
        await adding_value_to_position(
            make_callback_query(data="infinity_no", user_id=1), fsm_context
        )
        await collect_item_value(make_message(text="k1", user_id=1), fsm_context)

        call = make_callback_query(data="finish_adding_items", user_id=1)
        call.bot.send_message = AsyncMock(
            side_effect=TelegramForbiddenError(method=MagicMock(), message="blocked")
        )

        with patch('bot.handlers.admin.adding_position._parse_channel_username',
                   return_value="myshop"):
            await finish_adding_items_callback_handler(call, fsm_context)

        # The item is still created and the flow still completes.
        assert await get_item_info("BlockedChannelItem") is not None
        assert await fsm_context.get_state() is None


class TestFinishSingleValue:

    async def test_creates_an_infinite_stock_item(self, make_message, make_callback_query,
                                                  fsm_context, category_factory):
        await category_factory("AddCat")
        await _walk_to_infinity_question(make_message, fsm_context, name="InfiniteItem")
        await adding_value_to_position(
            make_callback_query(data="infinity_yes", user_id=1), fsm_context
        )

        with patch('bot.handlers.admin.adding_position._parse_channel_username', return_value=None):
            await finish_adding_item_callback_handler(
                make_message(text="forever-key", user_id=1), fsm_context
            )

        assert await get_item_info("InfiniteItem") is not None
        assert await check_value("InfiniteItem") is True
        assert await fsm_context.get_state() is None

    async def test_blank_value_creates_nothing(self, make_message, make_callback_query,
                                               fsm_context, category_factory):
        await category_factory("AddCat")
        await _walk_to_infinity_question(make_message, fsm_context, name="NotCreated")
        await adding_value_to_position(
            make_callback_query(data="infinity_yes", user_id=1), fsm_context
        )

        await finish_adding_item_callback_handler(
            make_message(text="   ", user_id=1), fsm_context
        )

        assert await get_item_info("NotCreated") is None
        # Still waiting for a real value.
        assert await fsm_context.get_state() == AddItemFSM.waiting_single_value
