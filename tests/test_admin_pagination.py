import datetime

import pytest

from bot.database.methods.create import create_user
from tests.factories import add_referral_earning

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


def _button_labels(kwargs):
    """Button captions of the markup passed to edit_text."""
    markup = kwargs.get("reply_markup")
    if markup is None:
        return []
    return [b.text for row in markup.inline_keyboard for b in row]


async def _referrer_with_referral(referrer_id, referral_id):
    await create_user(referrer_id, NOW, referral_id=None, role=1)
    await create_user(referral_id, NOW, referral_id=referrer_id, role=1)
    await add_referral_earning(referrer_id, referral_id, amount=50, original_amount=500)


REFERRAL_VIEWS = [
    pytest.param(
        admin_view_referrals_handler, admin_referrals_pagination_handler,
        "admin-view-referrals_{uid}", "admin-refs-page_{uid}_0",
        "referrals.list.title", "referrals.list.empty",
        id="referrals",
    ),
    pytest.param(
        admin_view_all_earnings_handler, admin_all_earnings_pagination_handler,
        "admin-view-earnings_{uid}", "admin-all-earn_{uid}_page_0",
        "all.earnings.title", "all.earnings.empty",
        id="all-earnings",
    ),
]


@pytest.mark.parametrize(
    "view_handler,page_handler,view_cb,page_cb,title_key,empty_key", REFERRAL_VIEWS
)
class TestAdminReferralListViews:

    async def test_view_empty(self, make_callback_query, fsm_context, user_factory,
                              view_handler, page_handler, view_cb, page_cb,
                              title_key, empty_key):
        await user_factory(telegram_id=900001)
        call = make_callback_query(data=view_cb.format(uid=900001))
        await view_handler(call, fsm_context)
        text, _ = _last_edit(call)
        assert empty_key in text

    async def test_view_with_data(self, make_callback_query, fsm_context,
                                  view_handler, page_handler, view_cb, page_cb,
                                  title_key, empty_key):
        await _referrer_with_referral(900002, 900012)
        call = make_callback_query(data=view_cb.format(uid=900002))
        await view_handler(call, fsm_context)
        text, kwargs = _last_edit(call)
        assert title_key in text
        assert "900002" in text          # the referrer the list belongs to
        assert kwargs.get("reply_markup") is not None

    async def test_pagination(self, make_callback_query, fsm_context,
                              view_handler, page_handler, view_cb, page_cb,
                              title_key, empty_key):
        await _referrer_with_referral(900003, 900013)
        # seed state via the view handler, then page
        view = make_callback_query(data=view_cb.format(uid=900003))
        await view_handler(view, fsm_context)
        page = make_callback_query(data=page_cb.format(uid=900003))
        await page_handler(page, fsm_context)
        page_text, page_kwargs = _last_edit(page)
        view_text, _ = _last_edit(view)
        # Paging back to page 0 must reproduce the first page, not an empty list.
        assert page_text == view_text
        assert page_kwargs.get("reply_markup") is not None


# --- admin users list pair ---

class TestUsersListPagination:
    async def test_view(self, make_callback_query, fsm_context, user_factory):
        await user_factory(telegram_id=900201)
        call = make_callback_query(data="users_list")
        await users_callback_handler(call, fsm_context)
        _, kwargs = _last_edit(call)
        # The seeded user must actually be listed, not just "some markup exists".
        assert any("900201" in label for label in _button_labels(kwargs))

    async def test_navigate(self, make_callback_query, fsm_context, user_factory):
        await user_factory(telegram_id=900202)
        view = make_callback_query(data="users_list")
        await users_callback_handler(view, fsm_context)
        page = make_callback_query(data="users-page_0")
        await navigate_users(page, fsm_context)
        _, kwargs = _last_edit(page)
        assert any("900202" in label for label in _button_labels(kwargs))


# --- shop categories pair ---

class TestShopCategoriesPagination:
    async def test_view(self, make_callback_query, fsm_context, category_factory):
        await category_factory("CatA")
        call = make_callback_query(data="shop")
        await shop_callback_handler(call, fsm_context)
        _, kwargs = _last_edit(call)
        assert "CatA" in _button_labels(kwargs)

    async def test_navigate(self, make_callback_query, fsm_context, category_factory):
        await category_factory("CatB")
        view = make_callback_query(data="shop")
        await shop_callback_handler(view, fsm_context)
        page = make_callback_query(data="categories-page_0")
        await navigate_categories(page, fsm_context)
        _, kwargs = _last_edit(page)
        assert "CatB" in _button_labels(kwargs)


# --- shop goods pair ---

class TestShopGoodsPagination:
    async def test_list_and_navigate(self, make_callback_query, fsm_context, item_factory):
        await item_factory(name="G1", category="GoodsCat", values=[("v", False)])
        # open categories -> select category (cat:0:0) -> paginate goods (gp_0)
        c1 = make_callback_query(data="shop")
        await shop_callback_handler(c1, fsm_context)
        c2 = make_callback_query(data="cat:0:0")
        await items_list_callback_handler(c2, fsm_context)
        _, kwargs2 = _last_edit(c2)
        assert any("G1" in label for label in _button_labels(kwargs2))
        c3 = make_callback_query(data="gp_0")
        await navigate_goods(c3, fsm_context)
        _, kwargs3 = _last_edit(c3)
        assert any("G1" in label for label in _button_labels(kwargs3))


# --- profile views (two independent implementations) ---

class TestProfileViews:
    async def test_user_profile_view_rich(self, make_callback_query, user_factory):
        await user_factory(telegram_id=900301)
        call = make_callback_query(data="check-user_900301", user_id=900301)
        await user_profile_view(call)
        text, kwargs = _last_edit(call)
        assert kwargs.get("reply_markup") is not None
        assert "900301" in text

    async def test_show_user_info_readonly(self, make_callback_query, user_factory):
        await user_factory(telegram_id=900302)
        call = make_callback_query(data="show-user_user-900302", user_id=900302)
        await show_user_info(call)
        text, kwargs = _last_edit(call)
        assert kwargs.get("reply_markup") is not None
        assert "900302" in text


class TestEveryNavPrefixHasAHandler:
    # (module, nav prefix a handler must accept, a concrete payload it produces)
    NAV_PREFIXES = [
        ("bot.handlers.user.referral_system", "ref-earn_", "ref-earn_123_1"),
        ("bot.handlers.user.referral_system", "referrals_page_", "referrals_page_1"),
        ("bot.handlers.user.referral_system", "all_earnings_page_", "all_earnings_page_1"),
        ("bot.handlers.admin.user_management", "admin-refearn_", "admin-refearn_1_2_1"),
        ("bot.handlers.admin.user_management", "admin-refs-page_", "admin-refs-page_1_1"),
        ("bot.handlers.admin.user_management", "admin-all-earn_", "admin-all-earn_1_page_1"),
        ("bot.handlers.admin.user_management", "bought-goods-page_", "bought-goods-page_user_0"),
        ("bot.handlers.admin.shop_management", "users-page_", "users-page_1"),
        ("bot.handlers.user.shop_and_goods", "categories-page_", "categories-page_1"),
        ("bot.handlers.user.shop_and_goods", "gp_", "gp_1"),
        ("bot.handlers.user.shop_and_goods", "sp_", "sp_1"),
        ("bot.handlers.admin.goods_management", "gip_", "gip_abcd1234_1"),
        ("bot.handlers.admin.promo_management", "promos-page_", "promos-page_1"),
    ]

    def _all_routers(self):
        from bot.handlers.admin import router as admin_router
        from bot.handlers.user import router as user_router
        from bot.handlers.other import router as other_router
        return [admin_router, user_router, other_router]

    def _matches(self, payload: str) -> bool:
        """Whether any registered callback_query handler's filters accept payload."""
        from aiogram.types import CallbackQuery
        from unittest.mock import MagicMock

        call = MagicMock(spec=CallbackQuery)
        call.data = payload

        def walk(router):
            yield router
            for sub in router.sub_routers:
                yield from walk(sub)

        for root in self._all_routers():
            for router in walk(root):
                for handler in router.callback_query.handlers:
                    for f in handler.filters or ():
                        # Only the F.data magic filters describe the payload shape.
                        # Permission filters and state filters are separate
                        # concerns and are deliberately ignored here.
                        magic = getattr(f, "magic", None)
                        if magic is None:
                            continue
                        try:
                            if magic.resolve(call):
                                return True
                        except Exception:
                            continue
        return False

    def test_generated_nav_payloads_are_routable(self):
        unroutable = [
            (module, prefix, payload)
            for module, prefix, payload in self.NAV_PREFIXES
            if not self._matches(payload)
        ]
        assert not unroutable, f"nav payloads with no handler: {unroutable}"

    def test_the_probe_itself_detects_an_unrouted_payload(self):
        """Guard against the check silently passing everything."""
        assert self._matches("definitely-not-a-registered-prefix_1") is False

    def test_probe_flags_the_two_historically_dead_prefixes(self):
        """The prefixes these views used to generate had no handler at all.

        Kept as a proof that the check above can actually fail — if either of
        these ever became routable the probe would have stopped discriminating.
        """
        assert self._matches("ref_earnings_123_page_1") is False
        assert self._matches("admin-ref-earn_1_2_page_1") is False
