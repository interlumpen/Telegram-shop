import pytest
from unittest.mock import patch, AsyncMock, MagicMock


class TestCartHandlers:
    async def test_stepper_increments_and_rerenders(self, make_callback_query, fsm_context,
                                                    user_factory, item_factory):
        from bot.handlers.user.cart import cart_qty_handler
        from bot.database.methods.create import add_to_cart
        from bot.database.methods.read import get_cart_items, get_cart_count

        await user_factory(telegram_id=620001, balance=1000)
        await item_factory(name="StepItem", price=100, values=[("v", False)])
        await add_to_cart(620001, "StepItem")
        cid = (await get_cart_items(620001))[0]["id"]

        call = make_callback_query(data=f"cart_qty:{cid}:1", user_id=620001)
        await cart_qty_handler(call, fsm_context)

        assert await get_cart_count(620001) == 2
        call.message.edit_text.assert_called()          # cart re-rendered
        text = call.message.edit_text.call_args[0][0]
        assert "×2" in text                              # quantity shown to the user

    async def test_stepper_down_to_zero_removes_line(self, make_callback_query, fsm_context,
                                                     user_factory, item_factory):
        from bot.handlers.user.cart import cart_qty_handler
        from bot.database.methods.create import add_to_cart
        from bot.database.methods.read import get_cart_items

        await user_factory(telegram_id=620002, balance=1000)
        await item_factory(name="DropItem", price=100, values=[("v", False)])
        await add_to_cart(620002, "DropItem")
        cid = (await get_cart_items(620002))[0]["id"]

        call = make_callback_query(data=f"cart_qty:{cid}:-1", user_id=620002)
        await cart_qty_handler(call, fsm_context)

        assert await get_cart_items(620002) == []
        # Re-rendered as an empty cart: no stepper buttons left.
        markup = call.message.edit_text.call_args[1]["reply_markup"]
        cbs = [b.callback_data for row in markup.inline_keyboard for b in row]
        assert not any(c and c.startswith("cart_qty:") for c in cbs)

    async def test_cart_total_multiplies_by_quantity(self, make_callback_query, fsm_context,
                                                     user_factory, item_factory):
        from bot.handlers.user.cart import view_cart_handler
        from bot.database.methods.create import add_to_cart

        await user_factory(telegram_id=620003, balance=1000)
        await item_factory(name="TotalItem", price=25, values=[("v", False)])
        await add_to_cart(620003, "TotalItem", quantity=4)

        call = make_callback_query(data="cart", user_id=620003)
        await view_cart_handler(call, fsm_context)

        text = call.message.edit_text.call_args[0][0]
        assert "100" in text          # 25 * 4, not 25
        assert "×4" in text

    async def test_cart_warns_when_a_line_promo_stopped_applying(self, make_callback_query,
                                                                 fsm_context, user_factory,
                                                                 item_factory):
        from datetime import datetime, timedelta, timezone
        from decimal import Decimal
        from bot.handlers.user.cart import view_cart_handler
        from bot.database.methods.create import add_to_cart
        from bot.database.main import Database
        from bot.database.models.main import PromoCodes

        await user_factory(telegram_id=620010, balance=1000)
        await item_factory(name="WarnItem", price=100, values=[("v", False)])
        async with Database().session() as s:
            s.add(PromoCodes(
                code="WARNEXP", discount_type="percent", discount_value=Decimal("10"),
                scope="global", is_active=True,
                expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
            ))
        await add_to_cart(620010, "WarnItem", promo_code="WARNEXP")

        call = make_callback_query(data="cart", user_id=620010)
        await view_cart_handler(call, fsm_context)

        text = call.message.edit_text.call_args[0][0]
        assert "⚠️" in text            # the line is flagged, not silently full-price
        assert "WARNEXP" in text        # and it names the promo to remove
        assert "100" in text            # charged at full price, no fake discount

    async def test_stepper_rejects_other_users_line(self, make_callback_query, fsm_context,
                                                    user_factory, item_factory):
        from bot.handlers.user.cart import cart_qty_handler
        from bot.database.methods.create import add_to_cart
        from bot.database.methods.read import get_cart_items, get_cart_count

        await user_factory(telegram_id=620004, balance=1000)
        await user_factory(telegram_id=620005, balance=1000)
        await item_factory(name="MineItem", price=10, values=[("v", False)])
        await add_to_cart(620004, "MineItem", quantity=2)
        cid = (await get_cart_items(620004))[0]["id"]

        call = make_callback_query(data=f"cart_qty:{cid}:1", user_id=620005)
        await cart_qty_handler(call, fsm_context)

        assert await get_cart_count(620004) == 2    # untouched
        call.answer.assert_called()


class TestBackButtonSurvivesSubFlows:
    """The card's Back button is gp_/sp_, and both pagers are state-filtered.

    Anything that drops the browsing state leaves that button silently dead.
    """

    async def test_notify_keeps_the_browsing_state(self, make_callback_query, fsm_context,
                                                   user_factory, item_factory):
        from bot.handlers.user.shop_and_goods import subscribe_stock_handler
        from bot.states import ShopStates

        await user_factory(telegram_id=650001)
        await item_factory(name="BellItem", price=10, values=[])
        await fsm_context.update_data(csrf_item="BellItem", item_back_data="sp_0")
        await fsm_context.set_state(ShopStates.viewing_search_results)

        call = make_callback_query(data="sub_stock", user_id=650001)
        await subscribe_stock_handler(call, fsm_context)

        assert await fsm_context.get_state() == ShopStates.viewing_search_results

    async def test_promo_then_back_to_item_restores_category_state(self, make_callback_query,
                                                                   fsm_context, user_factory,
                                                                   item_factory):
        from bot.handlers.user.shop_and_goods import apply_promo_handler, back_to_item_handler
        from bot.states import ShopStates

        await user_factory(telegram_id=650002)
        await item_factory(name="PromoBack", price=10, values=[("v", False)])
        await fsm_context.update_data(csrf_item="PromoBack", item_back_data="gp_0")
        await fsm_context.set_state(ShopStates.viewing_goods)

        await apply_promo_handler(make_callback_query(data="apply_promo", user_id=650002), fsm_context)
        await back_to_item_handler(make_callback_query(data="back_to_item", user_id=650002), fsm_context)

        # navigate_goods is filtered on this; None would make gp_0 a no-op.
        assert await fsm_context.get_state() == ShopStates.viewing_goods

    async def test_promo_then_back_to_item_restores_search_state(self, make_callback_query,
                                                                 fsm_context, user_factory,
                                                                 item_factory):
        from bot.handlers.user.shop_and_goods import apply_promo_handler, back_to_item_handler
        from bot.states import ShopStates

        await user_factory(telegram_id=650003)
        await item_factory(name="PromoBackS", price=10, values=[("v", False)])
        await fsm_context.update_data(csrf_item="PromoBackS", item_back_data="sp_0")
        await fsm_context.set_state(ShopStates.viewing_search_results)

        await apply_promo_handler(make_callback_query(data="apply_promo", user_id=650003), fsm_context)
        await back_to_item_handler(make_callback_query(data="back_to_item", user_id=650003), fsm_context)

        assert await fsm_context.get_state() == ShopStates.viewing_search_results

    async def test_applying_a_promo_code_restores_the_browsing_state(self, make_message,
                                                                     make_callback_query,
                                                                     fsm_context, user_factory,
                                                                     item_factory):
        from bot.handlers.user.shop_and_goods import apply_promo_handler, promo_code_text_handler
        from bot.states import ShopStates

        await user_factory(telegram_id=650004)
        await item_factory(name="PromoTyped", price=10, values=[("v", False)])
        await fsm_context.update_data(csrf_item="PromoTyped", item_back_data="gp_0")
        await fsm_context.set_state(ShopStates.viewing_goods)

        await apply_promo_handler(make_callback_query(data="apply_promo", user_id=650004), fsm_context)
        # An invalid code still has to hand the browsing state back.
        await promo_code_text_handler(make_message(text="NOSUCHCODE", user_id=650004), fsm_context)

        assert await fsm_context.get_state() == ShopStates.viewing_goods


class TestCheckoutReceipt:
    """A checkout delivers one row per unit; the receipt must not try to render
    a button for every one of them."""

    async def test_receipt_buttons_are_capped(self, make_callback_query, fsm_context,
                                              user_factory, item_factory):
        from bot.handlers.user.cart import cart_checkout_confirm_handler, RECEIPT_MAX_BUTTONS
        from bot.database.methods.create import add_to_cart

        qty = RECEIPT_MAX_BUTTONS + 15
        await user_factory(telegram_id=640001, balance=100000)
        await item_factory(name="BulkItem", price=1,
                           values=[(f"v{i}", False) for i in range(qty)])
        await add_to_cart(640001, "BulkItem", quantity=qty)

        call = make_callback_query(data="cart_checkout_confirm", user_id=640001)
        await cart_checkout_confirm_handler(call, fsm_context)

        markup = call.message.edit_text.call_args[1]["reply_markup"]
        total_buttons = sum(len(row) for row in markup.inline_keyboard)
        # capped items + "all purchases" + back
        assert total_buttons == RECEIPT_MAX_BUTTONS + 2

        cbs = [b.callback_data for row in markup.inline_keyboard for b in row]
        assert "bought_items" in cbs      # overflow defers to the paginated list
        assert "profile" in cbs

    async def test_repeated_units_are_numbered(self, make_callback_query, fsm_context,
                                               user_factory, item_factory):
        from bot.handlers.user.cart import cart_checkout_confirm_handler
        from bot.database.methods.create import add_to_cart

        await user_factory(telegram_id=640002, balance=1000)
        await item_factory(name="TwinItem", price=10,
                           values=[("a", False), ("b", False)])
        await add_to_cart(640002, "TwinItem", quantity=2)

        call = make_callback_query(data="cart_checkout_confirm", user_id=640002)
        await cart_checkout_confirm_handler(call, fsm_context)

        markup = call.message.edit_text.call_args[1]["reply_markup"]
        labels = [b.text for row in markup.inline_keyboard for b in row]
        # Two units of one position must be distinguishable.
        assert "📦 TwinItem (1)" in labels
        assert "📦 TwinItem (2)" in labels

    async def test_receipt_state_does_not_store_delivered_secrets(self, make_callback_query,
                                                                  fsm_context, user_factory,
                                                                  item_factory):
        from bot.handlers.user.cart import cart_checkout_confirm_handler
        from bot.database.methods.create import add_to_cart

        await user_factory(telegram_id=640003, balance=1000)
        await item_factory(name="SecretItem", price=10, values=[("SUPERSECRET", False)])
        await add_to_cart(640003, "SecretItem")

        call = make_callback_query(data="cart_checkout_confirm", user_id=640003)
        await cart_checkout_confirm_handler(call, fsm_context)

        stored = (await fsm_context.get_data())["cart_receipt_results"]
        assert all("value" not in r for r in stored)


class TestRestockButtonFlow:

    async def test_subscribe_from_item_card(self, make_callback_query, fsm_context,
                                            user_factory, item_factory):
        from bot.handlers.user.shop_and_goods import subscribe_stock_handler
        from bot.database.methods.read import is_subscribed_to_stock

        await user_factory(telegram_id=630001)
        await item_factory(name="EmptyItem", price=10, values=[])   # out of stock
        await fsm_context.update_data(csrf_item="EmptyItem")

        call = make_callback_query(data="sub_stock", user_id=630001)
        await subscribe_stock_handler(call, fsm_context)

        assert await is_subscribed_to_stock(630001, "EmptyItem") is True

    async def test_unsubscribe_from_item_card(self, make_callback_query, fsm_context,
                                              user_factory, item_factory):
        from bot.handlers.user.shop_and_goods import unsubscribe_stock_handler
        from bot.database.methods.create import subscribe_to_stock
        from bot.database.methods.read import is_subscribed_to_stock

        await user_factory(telegram_id=630002)
        await item_factory(name="EmptyItem2", price=10, values=[])
        await subscribe_to_stock(630002, "EmptyItem2")
        await fsm_context.update_data(csrf_item="EmptyItem2")

        call = make_callback_query(data="unsub_stock", user_id=630002)
        await unsubscribe_stock_handler(call, fsm_context)

        assert await is_subscribed_to_stock(630002, "EmptyItem2") is False

    async def test_subscribe_without_item_in_state(self, make_callback_query, fsm_context,
                                                   user_factory):
        from bot.handlers.user.shop_and_goods import subscribe_stock_handler

        await user_factory(telegram_id=630003)
        call = make_callback_query(data="sub_stock", user_id=630003)
        await subscribe_stock_handler(call, fsm_context)

        call.answer.assert_called_once()
        assert call.answer.call_args[1].get("show_alert") is True


class TestCatalogSearch:

    async def test_prompt_sets_state(self, make_callback_query, fsm_context):
        from bot.handlers.user.shop_and_goods import shop_search_handler
        from bot.states import ShopStates

        call = make_callback_query(data="shop_search", user_id=610001)
        await shop_search_handler(call, fsm_context)

        call.message.edit_text.assert_called_once()
        assert await fsm_context.get_state() == ShopStates.waiting_search_query

    async def test_query_renders_results(self, make_message, fsm_context, item_factory):
        from bot.handlers.user.shop_and_goods import receive_search_query_handler
        from bot.states import ShopStates

        await item_factory(name="Netflix Account", price=100, values=[("v", False)])
        await item_factory(name="Spotify Account", price=50, values=[("v", False)])
        await item_factory(name="Unrelated", price=10, values=[("v", False)])

        message = make_message(text="Account", user_id=610002)
        await receive_search_query_handler(message, fsm_context)

        message.answer.assert_called_once()
        data = await fsm_context.get_data()
        assert sorted(data["search_page_items"]) == ["Netflix Account", "Spotify Account"]
        assert data["search_query"] == "Account"
        assert await fsm_context.get_state() == ShopStates.viewing_search_results

    async def test_description_only_match_is_found(self, make_message, fsm_context, item_factory):
        """Proves the OR arm against description, not just name."""
        from bot.handlers.user.shop_and_goods import receive_search_query_handler

        await item_factory(name="Opaque Name", price=10,
                           description="a premium gamepass inside", values=[("v", False)])

        message = make_message(text="gamepass", user_id=610003)
        await receive_search_query_handler(message, fsm_context)

        data = await fsm_context.get_data()
        assert data["search_page_items"] == ["Opaque Name"]

    async def test_search_is_case_insensitive(self, make_message, fsm_context, item_factory):
        from bot.handlers.user.shop_and_goods import receive_search_query_handler

        await item_factory(name="UPPERCASE Item", price=10, values=[("v", False)])

        message = make_message(text="uppercase", user_id=610004)
        await receive_search_query_handler(message, fsm_context)

        data = await fsm_context.get_data()
        assert data["search_page_items"] == ["UPPERCASE Item"]

    async def test_empty_result(self, make_message, fsm_context, item_factory):
        from bot.handlers.user.shop_and_goods import receive_search_query_handler

        await item_factory(name="Something", price=10, values=[("v", False)])

        message = make_message(text="nothingmatchesthis", user_id=610005)
        await receive_search_query_handler(message, fsm_context)

        text = message.answer.call_args[0][0]
        assert "shop.search.empty" in text
        assert (await fsm_context.get_data()).get("search_page_items") is None

    async def test_too_short_query_stays_in_state(self, make_message, fsm_context):
        from bot.handlers.user.shop_and_goods import receive_search_query_handler
        from bot.states import ShopStates

        await fsm_context.set_state(ShopStates.waiting_search_query)
        message = make_message(text="a", user_id=610006)
        await receive_search_query_handler(message, fsm_context)

        text = message.answer.call_args[0][0]
        assert "shop.search.too_short" in text
        # Still waiting, so the user can just retype.
        assert await fsm_context.get_state() == ShopStates.waiting_search_query

    async def test_open_item_from_search_sets_back_to_results(self, make_callback_query,
                                                              fsm_context, item_factory):
        """Back from a search-opened card must return to the results, not categories."""
        from bot.handlers.user.shop_and_goods import search_item_info_handler

        await item_factory(name="FoundItem", price=100, values=[("v", False)])
        await fsm_context.update_data(search_query="found")

        call = make_callback_query(data="sitm:0:0", user_id=610007)
        await search_item_info_handler(call, fsm_context)

        data = await fsm_context.get_data()
        assert data["csrf_item"] == "FoundItem"
        assert data["item_back_data"] == "sp_0"

    async def test_open_item_bad_index(self, make_callback_query, fsm_context):
        from bot.handlers.user.shop_and_goods import search_item_info_handler

        await fsm_context.update_data(search_query="nothingmatches")
        call = make_callback_query(data="sitm:5:0", user_id=610008)
        await search_item_info_handler(call, fsm_context)

        call.answer.assert_called_once()
        assert call.answer.call_args[1].get("show_alert") is True


class TestSearchQueryEscaping:
    """LIKE wildcards typed by a user must be literals, not patterns."""

    async def test_underscore_is_literal(self, item_factory):
        from bot.database.methods.lazy_queries import query_goods_search

        await item_factory(name="a_b", price=10, values=[("v1", False)])
        await item_factory(name="axb", price=10, values=[("v2", False)])

        assert await query_goods_search("a_b") == ["a_b"]

    async def test_percent_is_literal(self, item_factory):
        from bot.database.methods.lazy_queries import query_goods_search

        await item_factory(name="100% cashback", price=10, values=[("v1", False)])
        await item_factory(name="plain item", price=10, values=[("v2", False)])

        assert await query_goods_search("100%") == ["100% cashback"]

    async def test_blank_query_returns_nothing(self, item_factory):
        from bot.database.methods.lazy_queries import query_goods_search

        await item_factory(name="Anything", price=10, values=[("v", False)])

        assert await query_goods_search("   ") == []
        assert await query_goods_search("   ", count_only=True) == 0

    async def test_count_only_matches_results(self, item_factory):
        from bot.database.methods.lazy_queries import query_goods_search

        for i in range(3):
            await item_factory(name=f"Bundle {i}", price=10, values=[(f"v{i}", False)])

        assert await query_goods_search("Bundle", count_only=True) == 3
        assert len(await query_goods_search("Bundle")) == 3


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
