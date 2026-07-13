from bot.database.methods.create import add_to_cart, create_review
from bot.database.methods.read import (
    get_cart_items, get_cart_count, get_item_avg_rating, get_user_review,
)
from bot.database.methods.delete import remove_from_cart, clear_cart
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
        await user_factory(telegram_id=960003)
        await item_factory(name="CartF", price=10, values=[("v", False)])
        for _ in range(10):
            await add_to_cart(960003, "CartF")
        ok, msg = await add_to_cart(960003, "CartF")
        assert (ok, msg) == (False, "cart_full")

    async def test_remove_and_clear(self, user_factory, item_factory):
        await user_factory(telegram_id=960004)
        await item_factory(name="CartR", price=10, values=[("v", False)])
        await add_to_cart(960004, "CartR")
        items = await get_cart_items(960004)
        assert await remove_from_cart(items[0]["id"], 960004) is True
        assert await get_cart_count(960004) == 0
        await add_to_cart(960004, "CartR")
        await add_to_cart(960004, "CartR")
        assert await clear_cart(960004) == 2


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
