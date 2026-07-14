import datetime

from bot.database.methods.create import create_user, create_referral_earning

from bot.handlers.admin.user_management import (
    admin_view_referrals_handler, admin_referrals_pagination_handler,
    admin_view_all_earnings_handler, admin_all_earnings_pagination_handler,
    user_profile_view,
)
from bot.handlers.admin.shop_management import (
    users_callback_handler, navigate_users, show_user_info,
)
from bot.handlers.user.shop_and_goods import (
    shop_callback_handler, navigate_categories,
    items_list_callback_handler, navigate_goods,
)

NOW = datetime.datetime.now(datetime.timezone.utc)


def _last_edit(call):
    """(text, kwargs) of the most recent edit_text call."""
    args, kwargs = call.message.edit_text.call_args
    return args[0], kwargs


async def _referrer_with_referral(referrer_id, referral_id):
    await create_user(referrer_id, NOW, referral_id=None, role=1)
    await create_user(referral_id, NOW, referral_id=referrer_id, role=1)
    await create_referral_earning(referrer_id, referral_id, amount=50, original_amount=500)


# --- admin referral list pair ---

class TestAdminReferralsPagination:
    async def test_view_empty(self, make_callback_query, fsm_context, user_factory):
        await user_factory(telegram_id=900001)
        call = make_callback_query(data="admin-view-referrals_900001")
        await admin_view_referrals_handler(call, fsm_context)
        text, _ = _last_edit(call)
        assert isinstance(text, str)  # empty-state message

    async def test_view_with_data(self, make_callback_query, fsm_context):
        await _referrer_with_referral(900002, 900012)
        call = make_callback_query(data="admin-view-referrals_900002")
        await admin_view_referrals_handler(call, fsm_context)
        text, kwargs = _last_edit(call)
        assert isinstance(text, str)
        assert kwargs.get("reply_markup") is not None
        assert (await fsm_context.get_data()).get("admin_referrals_paginator") is not None

    async def test_pagination(self, make_callback_query, fsm_context):
        await _referrer_with_referral(900003, 900013)
        # seed state via the view handler, then page
        view = make_callback_query(data="admin-view-referrals_900003")
        await admin_view_referrals_handler(view, fsm_context)
        page = make_callback_query(data="admin-refs-page_900003_0")
        await admin_referrals_pagination_handler(page, fsm_context)
        text, kwargs = _last_edit(page)
        assert isinstance(text, str)
        assert kwargs.get("reply_markup") is not None


# --- admin all-earnings pair ---

class TestAdminAllEarningsPagination:
    async def test_view_empty(self, make_callback_query, fsm_context, user_factory):
        await user_factory(telegram_id=900101)
        call = make_callback_query(data="admin-view-earnings_900101")
        await admin_view_all_earnings_handler(call, fsm_context)
        text, _ = _last_edit(call)
        assert isinstance(text, str)

    async def test_view_with_data(self, make_callback_query, fsm_context):
        await _referrer_with_referral(900102, 900112)
        call = make_callback_query(data="admin-view-earnings_900102")
        await admin_view_all_earnings_handler(call, fsm_context)
        text, kwargs = _last_edit(call)
        assert isinstance(text, str)
        assert kwargs.get("reply_markup") is not None
        assert (await fsm_context.get_data()).get("admin_all_earnings_paginator") is not None

    async def test_pagination(self, make_callback_query, fsm_context):
        await _referrer_with_referral(900103, 900113)
        view = make_callback_query(data="admin-view-earnings_900103")
        await admin_view_all_earnings_handler(view, fsm_context)
        page = make_callback_query(data="admin-all-earn_900103_page_0")
        await admin_all_earnings_pagination_handler(page, fsm_context)
        text, kwargs = _last_edit(page)
        assert isinstance(text, str)
        assert kwargs.get("reply_markup") is not None


# --- admin users list pair ---

class TestUsersListPagination:
    async def test_view(self, make_callback_query, fsm_context, user_factory):
        await user_factory(telegram_id=900201)
        call = make_callback_query(data="users_list")
        await users_callback_handler(call, fsm_context)
        text, kwargs = _last_edit(call)
        assert isinstance(text, str)
        assert kwargs.get("reply_markup") is not None
        assert (await fsm_context.get_data()).get("users_paginator") is not None

    async def test_navigate(self, make_callback_query, fsm_context, user_factory):
        await user_factory(telegram_id=900202)
        view = make_callback_query(data="users_list")
        await users_callback_handler(view, fsm_context)
        page = make_callback_query(data="users-page_0")
        await navigate_users(page, fsm_context)
        text, kwargs = _last_edit(page)
        assert isinstance(text, str)
        assert kwargs.get("reply_markup") is not None


# --- shop categories pair ---

class TestShopCategoriesPagination:
    async def test_view(self, make_callback_query, fsm_context, category_factory):
        await category_factory("CatA")
        call = make_callback_query(data="shop")
        await shop_callback_handler(call, fsm_context)
        text, kwargs = _last_edit(call)
        assert isinstance(text, str)
        assert kwargs.get("reply_markup") is not None
        assert (await fsm_context.get_data()).get("categories_paginator") is not None

    async def test_navigate(self, make_callback_query, fsm_context, category_factory):
        await category_factory("CatB")
        view = make_callback_query(data="shop")
        await shop_callback_handler(view, fsm_context)
        page = make_callback_query(data="categories-page_0")
        await navigate_categories(page, fsm_context)
        text, kwargs = _last_edit(page)
        assert isinstance(text, str)
        assert kwargs.get("reply_markup") is not None


# --- shop goods pair ---

class TestShopGoodsPagination:
    async def test_list_and_navigate(self, make_callback_query, fsm_context, item_factory):
        await item_factory(name="G1", category="GoodsCat", values=[("v", False)])
        # open categories -> select category (cat:0:0) -> paginate goods (gp_0)
        c1 = make_callback_query(data="shop")
        await shop_callback_handler(c1, fsm_context)
        c2 = make_callback_query(data="cat:0:0")
        await items_list_callback_handler(c2, fsm_context)
        text2, kwargs2 = _last_edit(c2)
        assert isinstance(text2, str)
        assert kwargs2.get("reply_markup") is not None
        c3 = make_callback_query(data="gp_0")
        await navigate_goods(c3, fsm_context)
        text3, kwargs3 = _last_edit(c3)
        assert isinstance(text3, str)
        assert kwargs3.get("reply_markup") is not None


# --- profile views (two independent implementations) ---

class TestProfileViews:
    async def test_user_profile_view_rich(self, make_callback_query, user_factory):
        await user_factory(telegram_id=900301)
        call = make_callback_query(data="check-user_900301", user_id=900301)
        await user_profile_view(call)
        text, kwargs = _last_edit(call)
        assert isinstance(text, str)
        assert kwargs.get("reply_markup") is not None
        assert "900301" in text

    async def test_show_user_info_readonly(self, make_callback_query, user_factory):
        await user_factory(telegram_id=900302)
        call = make_callback_query(data="show-user_user-900302", user_id=900302)
        await show_user_info(call)
        text, kwargs = _last_edit(call)
        assert isinstance(text, str)
        assert kwargs.get("reply_markup") is not None
        assert "900302" in text
