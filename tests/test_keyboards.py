import pytest

from bot.keyboards.inline import (
    main_menu, profile_keyboard, simple_buttons, back, close, item_info, payment_menu,
    get_payment_choice, question_buttons, check_sub, referral_system_keyboard,
    admin_console_keyboard, cart_keyboard, rating_keyboard,
)


def _all_callback_data(markup):
    """Extract all callback_data values from markup."""
    result = []
    for row in markup.inline_keyboard:
        for btn in row:
            if btn.callback_data:
                result.append(btn.callback_data)
    return result


def _all_button_texts(markup):
    """Extract all button texts from markup."""
    result = []
    for row in markup.inline_keyboard:
        for btn in row:
            result.append(btn.text)
    return result


def _has_url_button(markup):
    """Check if any button has a URL."""
    for row in markup.inline_keyboard:
        for btn in row:
            if btn.url:
                return True
    return False


class TestMainMenu:

    @pytest.mark.parametrize("callback", ["shop", "rules", "profile"])
    def test_basic_buttons_present(self, callback):
        assert callback in _all_callback_data(main_menu(role=1))

    @pytest.mark.parametrize("role,has_console", [
        (1, False),  # regular user
        (2, True),   # admin
    ])
    def test_console_button_follows_role(self, role, has_console):
        assert ("console" in _all_callback_data(main_menu(role=role))) is has_console

    @pytest.mark.parametrize("kwargs,expected", [
        ({"channel": "test_channel"}, True),
        ({"helper": "12345"}, True),
        ({}, False),
    ])
    def test_url_buttons(self, kwargs, expected):
        assert _has_url_button(main_menu(role=1, **kwargs)) is expected


class TestProfileKeyboard:

    @pytest.mark.parametrize("kwargs,callback,expected", [
        ({"referral_percent": 0, "user_items": 0}, "replenish_balance", True),
        ({"referral_percent": 0}, "back_to_menu", True),
        ({"referral_percent": 10}, "referral_system", True),
        ({"referral_percent": 0}, "referral_system", False),
        ({"referral_percent": 0, "user_items": 5}, "bought_items", True),
        ({"referral_percent": 0, "user_items": 0}, "bought_items", False),
    ])
    def test_conditional_buttons(self, kwargs, callback, expected):
        assert (callback in _all_callback_data(profile_keyboard(**kwargs))) is expected


class TestPaymentMenu:

    def test_payment_menu_has_pay_url(self):
        markup = payment_menu("https://example.com/pay")
        has_url = False
        for row in markup.inline_keyboard:
            for btn in row:
                if btn.url == "https://example.com/pay":
                    has_url = True
        assert has_url

    def test_payment_menu_has_check(self):
        markup = payment_menu("https://example.com/pay")
        cbs = _all_callback_data(markup)
        assert "check" in cbs


class TestItemInfoKeyboard:

    @pytest.mark.parametrize("callback", ["buy_item", "gp_0"])
    def test_has_buy_and_back(self, callback):
        assert callback in _all_callback_data(item_info("gp_0"))

    @pytest.mark.parametrize("kwargs,expected_sub,expected_unsub", [
        ({}, False, False),                                   # in stock: no notify button
        ({"out_of_stock": True}, True, False),                # offer to subscribe
        ({"out_of_stock": True, "subscribed": True}, False, True),  # offer to unsubscribe
    ])
    def test_restock_notify_button(self, kwargs, expected_sub, expected_unsub):
        cbs = _all_callback_data(item_info("gp_0", **kwargs))
        assert ("sub_stock" in cbs) is expected_sub
        assert ("unsub_stock" in cbs) is expected_unsub

    def test_review_buttons_carry_no_item_name(self):
        """Telegram caps callback_data at 64 bytes; a 100-char Cyrillic product
        name embedded in it made the whole card unopenable."""
        cbs = _all_callback_data(item_info("gp_0", review_count=3, has_purchased=True))
        assert "reviews:0" in cbs
        assert "review" in cbs
        assert all(len(cb.encode("utf-8")) <= 64 for cb in cbs)


class TestCartKeyboard:

    def _items(self):
        return [{"id": 7, "item_name": "Widget", "quantity": 3}]

    def test_has_quantity_stepper(self):
        cbs = _all_callback_data(cart_keyboard(self._items()))
        assert "cart_qty:7:1" in cbs
        assert "cart_qty:7:-1" in cbs

    def test_has_remove_checkout_and_clear(self):
        cbs = _all_callback_data(cart_keyboard(self._items()))
        assert "cart_remove:7" in cbs
        assert "cart_checkout" in cbs
        assert "cart_clear" in cbs

    def test_shows_quantity_in_label(self):
        markup = cart_keyboard(self._items())
        labels = [b.text for row in markup.inline_keyboard for b in row]
        assert any("×3" in t for t in labels)


class TestLazyPaginatedExtraRows:

    async def test_extra_row_is_rendered(self):
        from aiogram.types import InlineKeyboardButton
        from bot.keyboards.inline import lazy_paginated_keyboard
        from bot.misc import LazyPaginator

        async def _query(offset=0, limit=10, count_only=False):
            return 1 if count_only else ["OnlyCat"]

        markup = await lazy_paginated_keyboard(
            paginator=LazyPaginator(_query, per_page=10),
            item_text=lambda c: c,
            item_callback=lambda c: f"cat:0:0",
            page=0,
            back_cb="back_to_menu",
            nav_cb_prefix="categories-page_",
            extra_rows=[[InlineKeyboardButton(text="🔍", callback_data="shop_search")]],
        )
        assert "shop_search" in _all_callback_data(markup)

    async def test_without_extra_rows_output_is_unchanged(self):
        """The 6 existing call sites must be byte-identical."""
        from bot.keyboards.inline import lazy_paginated_keyboard
        from bot.misc import LazyPaginator

        async def _query(offset=0, limit=10, count_only=False):
            return 1 if count_only else ["OnlyCat"]

        def _kb():
            return lazy_paginated_keyboard(
                paginator=LazyPaginator(_query, per_page=10),
                item_text=lambda c: c,
                item_callback=lambda c: "cat:0:0",
                page=0,
                back_cb="back_to_menu",
                nav_cb_prefix="categories-page_",
            )

        markup = await _kb()
        assert _all_callback_data(markup) == ["cat:0:0", "back_to_menu"]


class TestSimpleButtons:

    def test_creates_buttons(self):
        markup = simple_buttons([("A", "a"), ("B", "b")])
        cbs = _all_callback_data(markup)
        assert "a" in cbs
        assert "b" in cbs

    def test_button_count(self):
        markup = simple_buttons([("A", "a"), ("B", "b"), ("C", "c")])
        total = sum(len(row) for row in markup.inline_keyboard)
        assert total == 3


class TestBackAndClose:

    @pytest.mark.parametrize("args,expected", [
        ((), "menu"),           # default target
        (("profile",), "profile"),
    ])
    def test_back(self, args, expected):
        assert expected in _all_callback_data(back(*args))

    def test_close_button(self):
        assert "close" in _all_callback_data(close())


class TestReferralSystemKeyboard:

    @pytest.mark.parametrize("has_referrals,has_earnings", [
        (False, False),
        (True, False),
        (False, True),
        (True, True),
    ])
    def test_buttons_follow_available_data(self, has_referrals, has_earnings):
        cbs = _all_callback_data(
            referral_system_keyboard(has_referrals=has_referrals, has_earnings=has_earnings)
        )
        assert ("view_referrals" in cbs) is has_referrals
        assert ("view_all_earnings" in cbs) is has_earnings
        assert "profile" in cbs  # back button is always there


class TestGetPaymentChoice:

    def test_has_all_methods(self):
        markup = get_payment_choice()
        cbs = _all_callback_data(markup)
        assert "pay_cryptopay" in cbs
        assert "pay_stars" in cbs
        assert "pay_fiat" in cbs
        assert "replenish_balance" in cbs  # back


class TestQuestionButtons:

    def test_has_yes_no_back(self):
        markup = question_buttons("confirm_delete", "shop")
        cbs = _all_callback_data(markup)
        assert "confirm_delete_yes" in cbs
        assert "confirm_delete_no" in cbs
        assert "shop" in cbs


class TestCheckSub:

    def test_has_channel_url(self):
        markup = check_sub("test_channel")
        has_url = False
        for row in markup.inline_keyboard:
            for btn in row:
                if btn.url and "test_channel" in btn.url:
                    has_url = True
        assert has_url

    def test_has_check_callback(self):
        markup = check_sub("test_channel")
        cbs = _all_callback_data(markup)
        assert "sub_channel_done" in cbs


class TestAdminConsoleKeyboard:

    def test_has_roles_button(self):
        markup = admin_console_keyboard()
        cbs = _all_callback_data(markup)
        assert "role_mgmt" in cbs

    def test_has_all_admin_buttons(self):
        markup = admin_console_keyboard()
        cbs = _all_callback_data(markup)
        assert "shop_management" in cbs
        assert "goods_management" in cbs
        assert "categories_management" in cbs
        assert "user_management" in cbs
        assert "send_message" in cbs
        assert "role_mgmt" in cbs

    def test_maintenance_toggle(self):
        markup_on = admin_console_keyboard(maintenance_mode=True)
        markup_off = admin_console_keyboard(maintenance_mode=False)
        texts_on = _all_button_texts(markup_on)
        texts_off = _all_button_texts(markup_off)
        # The maintenance button text should differ between states
        assert texts_on != texts_off


class TestCallbackDataFitsTelegramLimit:
    LONG_CYRILLIC = "Подарочный сертификат Steam на 1000 рублей регион свободный"
    LONG_ASCII = "S" * 100

    def _assert_all_fit(self, markup):
        for cb in _all_callback_data(markup):
            assert len(cb.encode("utf-8")) <= 64, f"too long ({len(cb.encode())}B): {cb!r}"

    def test_item_card_fits_with_every_button_shown(self):
        markup = item_info(
            "gp_0", avg_rating=4.5, review_count=7, has_purchased=True,
            out_of_stock=True, subscribed=False,
        )
        self._assert_all_fit(markup)

    def test_item_card_fits_with_promo_applied(self):
        self._assert_all_fit(item_info("gp_0", applied_promo="SUMMER-2026", review_count=3))

    def test_cart_keyboard_fits_for_long_names(self):
        for name in (self.LONG_CYRILLIC, self.LONG_ASCII):
            items = [{"id": 987654, "item_name": name, "quantity": 99}]
            self._assert_all_fit(cart_keyboard(items))

    def test_rating_keyboard_fits(self):
        self._assert_all_fit(rating_keyboard())
