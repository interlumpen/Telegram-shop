import pytest
from unittest.mock import patch, AsyncMock, MagicMock


class TestShopCategories:

    async def test_shop_shows_categories(self, make_callback_query, fsm_context, category_factory):
        from bot.handlers.user.shop_and_goods import shop_callback_handler

        await category_factory("Electronics")
        await category_factory("Clothing")

        call = make_callback_query(data="shop", user_id=600001)

        with patch('bot.handlers.user.shop_and_goods.lazy_paginated_keyboard', new_callable=AsyncMock) as mock_kb:
            mock_kb.return_value = MagicMock()
            await shop_callback_handler(call, fsm_context)

        call.message.edit_text.assert_called_once()
        text = call.message.edit_text.call_args[0][0]
        assert "shop" in text.lower() or "categories" in text.lower() or "shop.categories" in text
        state = await fsm_context.get_state()
        from bot.states import ShopStates
        assert state == ShopStates.viewing_categories

    async def test_navigate_categories_page(self, make_callback_query, fsm_context, category_factory):
        from bot.handlers.user.shop_and_goods import navigate_categories

        for i in range(15):
            await category_factory(f"Cat_{i}")

        call = make_callback_query(data="categories-page_1", user_id=600002)

        # Set up paginator state in FSM
        await fsm_context.update_data(categories_paginator=None)

        with patch('bot.handlers.user.shop_and_goods.lazy_paginated_keyboard', new_callable=AsyncMock) as mock_kb:
            mock_kb.return_value = MagicMock()
            await navigate_categories(call, fsm_context)

        call.message.edit_text.assert_called_once()


class TestItemsList:

    async def test_items_list_valid_category(self, make_callback_query, fsm_context, item_factory):
        from bot.handlers.user.shop_and_goods import items_list_callback_handler

        await item_factory(name="Widget", price=100, category="Widgets", values=[("w1", False)])

        call = make_callback_query(data="cat:0:0", user_id=600010)
        await fsm_context.update_data(category_page_items=["Widgets"])

        with patch('bot.handlers.user.shop_and_goods.lazy_paginated_keyboard', new_callable=AsyncMock) as mock_kb:
            mock_kb.return_value = MagicMock()
            await items_list_callback_handler(call, fsm_context)

        call.message.edit_text.assert_called_once()
        assert call.message.edit_text.call_args is not None
        data = await fsm_context.get_data()
        assert data['current_category'] == 'Widgets'

    async def test_items_list_invalid_index(self, make_callback_query, fsm_context):
        from bot.handlers.user.shop_and_goods import items_list_callback_handler

        call = make_callback_query(data="cat:5:0", user_id=600011)
        await fsm_context.update_data(category_page_items=["OnlyCat"])

        await items_list_callback_handler(call, fsm_context)

        call.answer.assert_called_once()


class TestItemInfo:

    async def test_item_info_display(self, make_callback_query, fsm_context, item_factory):
        from bot.handlers.user.shop_and_goods import item_info_callback_handler

        await item_factory(name="InfoItem", price=250, category="TestCat", values=[("val1", False)])

        call = make_callback_query(data="itm:0:0", user_id=600020)
        await fsm_context.update_data(
            goods_page_items=["InfoItem"],
            current_category="TestCat",
        )

        with patch('bot.main.security_middleware', None):
            await item_info_callback_handler(call, fsm_context)

        call.message.edit_text.assert_called_once()

    async def test_item_info_invalid_index(self, make_callback_query, fsm_context):
        from bot.handlers.user.shop_and_goods import item_info_callback_handler

        call = make_callback_query(data="itm:10:0", user_id=600021)
        await fsm_context.update_data(goods_page_items=["SomeItem"])

        await item_info_callback_handler(call, fsm_context)

        call.answer.assert_called_once()

    async def test_item_info_not_found_in_db(self, make_callback_query, fsm_context):
        from bot.handlers.user.shop_and_goods import item_info_callback_handler

        call = make_callback_query(data="itm:0:0", user_id=600022)
        await fsm_context.update_data(
            goods_page_items=["NonExistent"],
            current_category="TestCat",
        )

        await item_info_callback_handler(call, fsm_context)

        call.answer.assert_called_once()

    async def test_item_info_unlimited_quantity(self, make_callback_query, fsm_context, item_factory):
        from bot.handlers.user.shop_and_goods import item_info_callback_handler

        await item_factory(name="InfItem", price=50, category="InfCat", values=[("unlimited_val", True)])

        call = make_callback_query(data="itm:0:0", user_id=600023)
        await fsm_context.update_data(
            goods_page_items=["InfItem"],
            current_category="InfCat",
        )

        with patch('bot.main.security_middleware', None):
            await item_info_callback_handler(call, fsm_context)

        call.message.edit_text.assert_called_once()
        text = call.message.edit_text.call_args[0][0]
        assert "quantity_unlimited" in text


class TestBoughtItems:

    async def test_bought_items_empty(self, make_callback_query, fsm_context, user_factory):
        from bot.handlers.user.shop_and_goods import bought_items_callback_handler

        await user_factory(telegram_id=600030)

        call = make_callback_query(data="bought_items", user_id=600030)

        with patch('bot.handlers.user.shop_and_goods.lazy_paginated_keyboard', new_callable=AsyncMock) as mock_kb:
            mock_kb.return_value = MagicMock()
            await bought_items_callback_handler(call, fsm_context)

        call.message.edit_text.assert_called_once()
        text = call.message.edit_text.call_args[0][0]
        assert isinstance(text, str)

    async def test_bought_item_info_not_found(self, make_callback_query):
        from bot.handlers.user.shop_and_goods import bought_item_info_callback_handler

        call = make_callback_query(data="bought-item:99999:profile", user_id=600031)

        await bought_item_info_callback_handler(call)

        call.answer.assert_called_once()
