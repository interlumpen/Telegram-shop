import pytest

from bot.database.methods.create import (
    add_to_cart, create_review, subscribe_to_stock, CART_MAX_QTY_PER_ITEM,
)
from bot.database.methods.read import (
    get_cart_items, get_cart_count, get_item_avg_rating, get_user_review,
    is_subscribed_to_stock,
)
from bot.database.methods.update import set_cart_item_quantity
from bot.database.methods.delete import (
    remove_from_cart, clear_cart, unsubscribe_from_stock, pop_stock_subscribers,
)
from bot.database.methods.lazy_queries import query_item_reviews


class TestCart:
    async def test_add_and_get(self, user_factory, item_factory):
        await user_factory(telegram_id=960001)
        await item_factory(name="CartX", price=100, values=[("v", False)])
        ok, msg = await add_to_cart(960001, "CartX", promo_code="SAVE")
        assert (ok, msg) == (True, "success")
        items = await get_cart_items(960001)
        assert len(items) == 1
        assert items[0]["item_name"] == "CartX"   # name must still be returned
        assert items[0]["promo_code"] == "SAVE"
        assert await get_cart_count(960001) == 1

    async def test_add_nonexistent_item(self, user_factory):
        await user_factory(telegram_id=960002)
        ok, msg = await add_to_cart(960002, "Ghost")
        assert (ok, msg) == (False, "item_not_found")

    async def test_cart_full(self, user_factory, item_factory):
        """The cart caps *distinct* positions, not units."""
        await user_factory(telegram_id=960003)
        for i in range(10):
            await item_factory(name=f"CartF{i}", price=10, values=[("v", False)])
            ok, msg = await add_to_cart(960003, f"CartF{i}")
            assert (ok, msg) == (True, "success")

        await item_factory(name="CartFOver", price=10, values=[("v", False)])
        ok, msg = await add_to_cart(960003, "CartFOver")
        assert (ok, msg) == (False, "cart_full")

    async def test_add_same_item_increments_quantity(self, user_factory, item_factory):
        await user_factory(telegram_id=960005)
        await item_factory(name="CartQ", price=10, values=[("v", False)])
        for _ in range(10):
            ok, msg = await add_to_cart(960005, "CartQ")
            assert (ok, msg) == (True, "success")

        items = await get_cart_items(960005)
        assert len(items) == 1              # one row, not ten
        assert items[0]["quantity"] == 10
        assert await get_cart_count(960005) == 10   # badge counts units

    async def test_increment_works_when_cart_is_full(self, user_factory, item_factory):
        """A full cart still allows bumping something already in it."""
        await user_factory(telegram_id=960006)
        for i in range(10):
            await item_factory(name=f"CartB{i}", price=10, values=[("v", False)])
            await add_to_cart(960006, f"CartB{i}")

        ok, msg = await add_to_cart(960006, "CartB0")
        assert (ok, msg) == (True, "success")
        items = await get_cart_items(960006)
        assert len(items) == 10
        assert next(i for i in items if i["item_name"] == "CartB0")["quantity"] == 2

    async def test_add_to_cart_qty_cap(self, user_factory, item_factory):
        await user_factory(telegram_id=960007)
        await item_factory(name="CartCap", price=10, values=[("v", False)])
        ok, msg = await add_to_cart(960007, "CartCap", quantity=CART_MAX_QTY_PER_ITEM)
        assert (ok, msg) == (True, "success")

        ok, msg = await add_to_cart(960007, "CartCap")
        assert (ok, msg) == (False, "cart_qty_max")
        assert await get_cart_count(960007) == CART_MAX_QTY_PER_ITEM

    async def test_remove_and_clear(self, user_factory, item_factory):
        await user_factory(telegram_id=960004)
        await item_factory(name="CartR", price=10, values=[("v", False)])
        await add_to_cart(960004, "CartR")
        items = await get_cart_items(960004)
        assert await remove_from_cart(items[0]["id"], 960004) is True
        assert await get_cart_count(960004) == 0
        # Two adds of one item are now a single row of quantity 2.
        await add_to_cart(960004, "CartR")
        await add_to_cart(960004, "CartR")
        assert await get_cart_count(960004) == 2
        assert await clear_cart(960004) == 1


class TestCartQuantity:
    async def test_increment_and_decrement(self, user_factory, item_factory):
        await user_factory(telegram_id=961001)
        await item_factory(name="QtyA", price=10, values=[("v", False)])
        await add_to_cart(961001, "QtyA", quantity=3)
        cid = (await get_cart_items(961001))[0]["id"]

        ok, code, qty = await set_cart_item_quantity(cid, 961001, 2)
        assert (ok, code, qty) == (True, "success", 5)

        ok, code, qty = await set_cart_item_quantity(cid, 961001, -1)
        assert (ok, code, qty) == (True, "success", 4)
        assert await get_cart_count(961001) == 4

    async def test_decrement_to_zero_removes_row(self, user_factory, item_factory):
        await user_factory(telegram_id=961002)
        await item_factory(name="QtyB", price=10, values=[("v", False)])
        await add_to_cart(961002, "QtyB")
        cid = (await get_cart_items(961002))[0]["id"]

        ok, code, qty = await set_cart_item_quantity(cid, 961002, -1)
        assert (ok, code, qty) == (True, "removed", 0)
        assert await get_cart_items(961002) == []

    async def test_cap_is_enforced(self, user_factory, item_factory):
        await user_factory(telegram_id=961003)
        await item_factory(name="QtyC", price=10, values=[("v", False)])
        await add_to_cart(961003, "QtyC", quantity=CART_MAX_QTY_PER_ITEM)
        cid = (await get_cart_items(961003))[0]["id"]

        ok, code, qty = await set_cart_item_quantity(cid, 961003, 1)
        assert (ok, code) == (False, "cart_qty_max")
        assert qty == CART_MAX_QTY_PER_ITEM

    async def test_other_users_cart_is_rejected(self, user_factory, item_factory):
        await user_factory(telegram_id=961004)
        await user_factory(telegram_id=961005)
        await item_factory(name="QtyD", price=10, values=[("v", False)])
        await add_to_cart(961004, "QtyD", quantity=2)
        cid = (await get_cart_items(961004))[0]["id"]

        ok, code, _ = await set_cart_item_quantity(cid, 961005, 1)
        assert (ok, code) == (False, "item_not_found")
        assert await get_cart_count(961004) == 2   # untouched

    async def test_one_row_per_user_item(self, user_factory, item_factory):
        """The unique constraint is what makes a cart line == one position."""
        from sqlalchemy.exc import IntegrityError
        from bot.database import Database
        from bot.database.models.main import CartItems

        await user_factory(telegram_id=961006)
        await item_factory(name="QtyE", price=10, values=[("v", False)])
        await add_to_cart(961006, "QtyE")
        item_id = (await get_cart_items(961006))[0]["item_id"]

        with pytest.raises(IntegrityError):
            async with Database().session() as s:
                s.add(CartItems(user_id=961006, item_id=item_id, quantity=1))


class TestStockSubscriptions:
    async def test_subscribe_and_check(self, user_factory, item_factory):
        await user_factory(telegram_id=962001)
        await item_factory(name="SubA", price=10, values=[])

        ok, code = await subscribe_to_stock(962001, "SubA")
        assert (ok, code) == (True, "subscribed")
        assert await is_subscribed_to_stock(962001, "SubA") is True

    async def test_subscribe_is_idempotent(self, user_factory, item_factory):
        await user_factory(telegram_id=962002)
        await item_factory(name="SubB", price=10, values=[])

        assert await subscribe_to_stock(962002, "SubB") == (True, "subscribed")
        assert await subscribe_to_stock(962002, "SubB") == (True, "already_subscribed")
        assert len(await pop_stock_subscribers("SubB")) == 1   # not two rows

    async def test_subscribe_unknown_item(self, user_factory):
        await user_factory(telegram_id=962003)
        assert await subscribe_to_stock(962003, "NoSuchItem") == (False, "item_not_found")

    async def test_unsubscribe(self, user_factory, item_factory):
        await user_factory(telegram_id=962004)
        await item_factory(name="SubC", price=10, values=[])
        await subscribe_to_stock(962004, "SubC")

        assert await unsubscribe_from_stock(962004, "SubC") is True
        assert await is_subscribed_to_stock(962004, "SubC") is False
        assert await unsubscribe_from_stock(962004, "SubC") is False   # already gone

    async def test_pop_returns_subscribers_and_empties_table(self, user_factory, item_factory):
        await user_factory(telegram_id=962005)
        await user_factory(telegram_id=962006)
        await item_factory(name="SubD", price=10, values=[])
        await subscribe_to_stock(962005, "SubD")
        await subscribe_to_stock(962006, "SubD")

        popped = await pop_stock_subscribers("SubD")
        assert sorted(popped) == [962005, 962006]
        assert await is_subscribed_to_stock(962005, "SubD") is False

    async def test_pop_twice_never_double_notifies(self, user_factory, item_factory):
        """The property that stops two concurrent restocks messaging twice."""
        await user_factory(telegram_id=962007)
        await item_factory(name="SubE", price=10, values=[])
        await subscribe_to_stock(962007, "SubE")

        assert await pop_stock_subscribers("SubE") == [962007]
        assert await pop_stock_subscribers("SubE") == []

    async def test_pop_unknown_item(self):
        assert await pop_stock_subscribers("NoSuchItem") == []

    async def test_subscriptions_are_per_item(self, user_factory, item_factory):
        await user_factory(telegram_id=962008)
        await item_factory(name="SubF", price=10, values=[])
        await item_factory(name="SubG", price=10, values=[])
        await subscribe_to_stock(962008, "SubF")

        assert await is_subscribed_to_stock(962008, "SubG") is False
        assert await pop_stock_subscribers("SubG") == []


class TestReviews:
    async def test_create_and_read(self, user_factory, item_factory):
        await user_factory(telegram_id=960010)
        await item_factory(name="RevX", price=100, values=[("v", False)])
        rid = await create_review(960010, "RevX", 4, "good")
        assert rid is not None
        # one review per user per item
        assert await create_review(960010, "RevX", 5, "again") is None
        review = await get_user_review(960010, "RevX")
        assert review["rating"] == 4
        assert review["text"] == "good"
        assert await get_item_avg_rating("RevX") == 4.0
        assert await query_item_reviews("RevX", count_only=True) == 1
        assert len(await query_item_reviews("RevX")) == 1

    async def test_avg_rating_none_when_empty(self, item_factory):
        await item_factory(name="RevEmpty", price=10, values=[("v", False)])
        assert await get_item_avg_rating("RevEmpty") is None

    async def test_avg_of_multiple(self, user_factory, item_factory):
        await item_factory(name="RevM", price=10, values=[("v", False)])
        await user_factory(telegram_id=960020)
        await user_factory(telegram_id=960021)
        await create_review(960020, "RevM", 2)
        await create_review(960021, "RevM", 4)
        assert await get_item_avg_rating("RevM") == 3.0

    async def test_get_user_review_none(self, user_factory, item_factory):
        await user_factory(telegram_id=960030)
        await item_factory(name="RevN", price=10, values=[("v", False)])
        assert await get_user_review(960030, "RevN") is None


class TestRenameKeepsLinks:
    async def test_rename_keeps_review_and_cart(self, user_factory, item_factory):
        from bot.database.methods.update import update_item

        await user_factory(telegram_id=970001, balance=1000)
        await item_factory(name="RenOld", price=10, category="RenCat", values=[("v", False)])
        await create_review(970001, "RenOld", 5, "great")
        await add_to_cart(970001, "RenOld")

        ok, err = await update_item("RenOld", "RenNew", "desc", 10, "RenCat")
        assert (ok, err) == (True, None)

        # review followed the rename
        assert await get_item_avg_rating("RenNew") == 5.0
        assert await get_item_avg_rating("RenOld") is None
        assert await get_user_review(970001, "RenNew") is not None
        # cart followed the rename
        items = await get_cart_items(970001)
        assert len(items) == 1
        assert items[0]["item_name"] == "RenNew"


class TestReviewRatingValidation:
    async def test_create_review_refuses_out_of_range_rating(self, user_factory, item_factory):
        from bot.database.methods.create import create_review

        await user_factory(telegram_id=700501)
        await item_factory(name="RatedItem", price=10)

        assert await create_review(700501, "RatedItem", 0) is None
        assert await create_review(700501, "RatedItem", 6) is None
        assert await create_review(700501, "RatedItem", 99) is None
        # The valid case still works, so nothing was over-restricted.
        assert await create_review(700501, "RatedItem", 5) is not None

    async def test_create_review_refuses_missing_item_name(self, user_factory):
        from bot.database.methods.create import create_review

        await user_factory(telegram_id=700502)
        assert await create_review(700502, "", 5) is None
        assert await create_review(700502, None, 5) is None

    async def test_forged_rating_callback_is_rejected(self, make_callback_query, fsm_context):
        from bot.handlers.user.shop_and_goods import receive_rating_handler

        for payload in ("rating:99", "rating:0", "rating:abc", "rating:"):
            call = make_callback_query(data=payload, user_id=700503)
            await receive_rating_handler(call, fsm_context)
            call.answer.assert_called()
            # Nothing was stashed for a later create_review call.
            assert (await fsm_context.get_data()).get("review_rating") is None

    async def test_submit_with_empty_state_reports_failure(self, make_callback_query, fsm_context):
        """An expired session leaves item/rating unset; that must not crash."""
        from bot.handlers.user.shop_and_goods import skip_review_text_handler

        call = make_callback_query(data="skip_review_text", user_id=700504)
        await skip_review_text_handler(call, fsm_context)

        call.message.edit_text.assert_called_once()
        assert "errors.something_wrong" in call.message.edit_text.call_args[0][0]
