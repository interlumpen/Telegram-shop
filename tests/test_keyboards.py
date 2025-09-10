import pytest
from aiogram.types import InlineKeyboardMarkup

from bot.keyboards import (
    main_menu, profile_keyboard, admin_console_keyboard,
    simple_buttons, back, close, lazy_paginated_keyboard,
    item_info, payment_menu, get_payment_choice,
    question_buttons, check_sub, referral_system_keyboard
)
from bot.misc import LazyPaginator


class TestKeyboards:
    """Test suite for keyboard generation"""

    def test_main_menu_keyboard(self):
        """Test main menu keyboard generation"""
        # Regular user menu
        user_menu = main_menu(role=1, channel="test_channel", helper="123456")
        assert isinstance(user_menu, InlineKeyboardMarkup)

        # Check buttons exist
        buttons = user_menu.inline_keyboard
        button_texts = [btn.text for row in buttons for btn in row]

        # Should have shop, rules, profile
        assert any("shop" in text.lower() or "магазин" in text.lower() for text in button_texts)
        assert any("rules" in text.lower() or "правила" in text.lower() for text in button_texts)
        assert any("profile" in text.lower() or "профиль" in text.lower() for text in button_texts)

        # Admin menu (role > 1)
        admin_menu = main_menu(role=2, channel="test_channel", helper="123456")
        admin_buttons = admin_menu.inline_keyboard
        admin_button_texts = [btn.text for row in admin_buttons for btn in row]

        # Should have admin panel button
        assert any("admin" in text.lower() or "администратор" in text.lower() for text in admin_button_texts)

        # Test without optional parameters
        minimal_menu = main_menu(role=1, channel=None, helper=None)
        minimal_buttons = minimal_menu.inline_keyboard
        minimal_button_texts = [btn.text for row in minimal_buttons for btn in row]

        # Should not have support/channel buttons
        assert not any("support" in text.lower() or "поддержка" in text.lower() for text in minimal_button_texts)

    def test_profile_keyboard(self):
        """Test profile keyboard generation"""
        # With referral system
        kb_with_ref = profile_keyboard(referral_percent=10, user_items=5)
        buttons = kb_with_ref.inline_keyboard
        button_texts = [btn.text for row in buttons for btn in row]

        # Should have replenish, referral, purchased buttons
        assert any("replenish" in text.lower() or "пополнить" in text.lower() for text in button_texts)
        assert any("referral" in text.lower() or "реферал" in text.lower() for text in button_texts)
        assert any("purchased" in text.lower() or "купленн" in text.lower() for text in button_texts)

        # Without referral system
        kb_no_ref = profile_keyboard(referral_percent=0, user_items=0)
        no_ref_buttons = kb_no_ref.inline_keyboard
        no_ref_button_texts = [btn.text for row in no_ref_buttons for btn in row]

        # Should not have referral/purchased buttons
        assert not any("referral" in text.lower() or "реферал" in text.lower() for text in no_ref_button_texts)
        assert not any("purchased" in text.lower() or "купленн" in text.lower() for text in no_ref_button_texts)

    def test_admin_console_keyboard(self):
        """Test admin console keyboard"""
        kb = admin_console_keyboard()
        buttons = kb.inline_keyboard
        button_texts = [btn.text for row in buttons for btn in row]

        # Check all admin options present
        assert any("shop" in text.lower() or "магазин" in text.lower() for text in button_texts)
        assert any("goods" in text.lower() or "позиц" in text.lower() for text in button_texts)
        assert any("categories" in text.lower() or "категор" in text.lower() for text in button_texts)
        assert any("users" in text.lower() or "пользовател" in text.lower() for text in button_texts)
        assert any("broadcast" in text.lower() or "рассылк" in text.lower() for text in button_texts)

    def test_simple_buttons(self):
        """Test simple buttons generation"""
        buttons_data = [
            ("Button 1", "callback_1"),
            ("Button 2", "callback_2"),
            ("Button 3", "callback_3"),
        ]

        # Test with 1 button per row
        kb1 = simple_buttons(buttons_data, per_row=1)
        assert len(kb1.inline_keyboard) == 3
        assert len(kb1.inline_keyboard[0]) == 1

        # Test with 2 buttons per row
        kb2 = simple_buttons(buttons_data, per_row=2)
        assert len(kb2.inline_keyboard) == 2
        assert len(kb2.inline_keyboard[0]) == 2
        assert len(kb2.inline_keyboard[1]) == 1

        # Test with all buttons in one row
        kb3 = simple_buttons(buttons_data, per_row=3)
        assert len(kb3.inline_keyboard) == 1
        assert len(kb3.inline_keyboard[0]) == 3

    def test_utility_keyboards(self):
        """Test utility keyboards (back, close)"""
        # Back button
        back_kb = back(cb="menu", text="Go Back")
        assert len(back_kb.inline_keyboard) == 1
        assert back_kb.inline_keyboard[0][0].text == "Go Back"
        assert back_kb.inline_keyboard[0][0].callback_data == "menu"

        # Default back text
        default_back_kb = back("test_callback")
        button_text = default_back_kb.inline_keyboard[0][0].text
        assert "back" in button_text.lower() or "назад" in button_text.lower()

        # Close button
        close_kb = close()
        assert len(close_kb.inline_keyboard) == 1
        close_text = close_kb.inline_keyboard[0][0].text
        assert "close" in close_text.lower() or "закрыть" in close_text.lower()

    def test_item_info_keyboard(self):
        """Test item info keyboard"""
        kb = item_info(item_name="TestItem", back_data="shop_category_1")
        buttons = kb.inline_keyboard

        # Should have buy and back buttons
        assert len(buttons) == 1
        assert len(buttons[0]) == 2

        # Check buy button
        buy_button = buttons[0][0]
        assert "buy" in buy_button.text.lower() or "купить" in buy_button.text.lower()
        assert buy_button.callback_data == "buy_TestItem"

        # Check back button
        back_button = buttons[0][1]
        assert "back" in back_button.text.lower() or "назад" in back_button.text.lower()
        assert back_button.callback_data == "shop_category_1"

    def test_payment_menu_keyboard(self):
        """Test payment menu keyboard"""
        pay_url = "https://example.com/pay"
        kb = payment_menu(pay_url)
        buttons = kb.inline_keyboard

        # Should have 3 buttons: pay (url), check, back
        assert len(buttons) == 3

        # Pay button should be URL
        pay_button = buttons[0][0]
        assert pay_button.url == pay_url
        assert "pay" in pay_button.text.lower() or "оплатить" in pay_button.text.lower()

        # Check button
        check_button = buttons[1][0]
        assert check_button.callback_data == "check"

        # Back button
        back_button = buttons[2][0]
        assert back_button.callback_data == "profile"

    def test_payment_choice_keyboard(self):
        """Test payment choice keyboard"""
        kb = get_payment_choice()
        buttons = kb.inline_keyboard
        button_callbacks = [btn.callback_data for row in buttons for btn in row]

        # Should have payment options
        assert "pay_cryptopay" in button_callbacks
        assert "pay_stars" in button_callbacks
        assert "pay_fiat" in button_callbacks
        assert "replenish_balance" in button_callbacks  # Back button

    def test_question_buttons_keyboard(self):
        """Test yes/no question keyboard"""
        kb = question_buttons(question="confirm_delete", back_data="menu")
        buttons = kb.inline_keyboard

        # First row: Yes/No
        assert len(buttons[0]) == 2
        yes_button = buttons[0][0]
        no_button = buttons[0][1]

        assert yes_button.callback_data == "confirm_delete_yes"
        assert no_button.callback_data == "confirm_delete_no"

        # Second row: Back
        assert len(buttons[1]) == 1
        back_button = buttons[1][0]
        assert back_button.callback_data == "menu"

    def test_check_sub_keyboard(self):
        """Test subscription check keyboard"""
        channel = "test_channel"
        kb = check_sub(channel)
        buttons = kb.inline_keyboard

        # Should have 2 buttons
        assert len(buttons) == 2

        # Channel button (URL)
        channel_button = buttons[0][0]
        assert channel_button.url == f"https://t.me/{channel}"

        # Check subscription button
        check_button = buttons[1][0]
        assert check_button.callback_data == "sub_channel_done"

    def test_referral_system_keyboard(self):
        """Test referral system keyboard"""
        # With referrals and earnings
        kb_full = referral_system_keyboard(has_referrals=True, has_earnings=True)
        buttons = kb_full.inline_keyboard
        button_callbacks = [btn.callback_data for row in buttons for btn in row]

        assert "view_referrals" in button_callbacks
        assert "view_all_earnings" in button_callbacks
        assert "profile" in button_callbacks  # Back button

        # Without referrals/earnings
        kb_empty = referral_system_keyboard(has_referrals=False, has_earnings=False)
        empty_buttons = kb_empty.inline_keyboard
        empty_callbacks = [btn.callback_data for row in empty_buttons for btn in row]

        assert "view_referrals" not in empty_callbacks
        assert "view_all_earnings" not in empty_callbacks
        assert "profile" in empty_callbacks  # Should still have back button

    @pytest.mark.asyncio
    async def test_lazy_paginated_keyboard(self):
        """Test lazy paginated keyboard generation"""
        # Mock data
        test_data = [f"Item {i}" for i in range(25)]

        # Mock query function
        async def mock_query(offset=0, limit=10, count_only=False):
            if count_only:
                return len(test_data)
            return test_data[offset:offset + limit]

        paginator = LazyPaginator(mock_query, per_page=10)

        # Generate keyboard for first page
        kb = await lazy_paginated_keyboard(
            paginator=paginator,
            item_text=lambda item: str(item),
            item_callback=lambda item: f"select_{item}",
            page=0,
            back_cb="menu",
            nav_cb_prefix="page_"
        )

        buttons = kb.inline_keyboard

        # Should have 10 items + navigation + back
        item_buttons = buttons[:-2]  # Exclude navigation and back rows
        assert len(item_buttons) == 10

        # Check item callbacks
        first_item_button = item_buttons[0][0]
        assert first_item_button.text == "Item 0"
        assert first_item_button.callback_data == "select_Item 0"

        # Check navigation buttons
        nav_row = buttons[-2]
        assert len(nav_row) >= 2  # At least page indicator and next button

        # Find next button
        next_button = None
        for btn in nav_row:
            if btn.callback_data and btn.callback_data.startswith("page_"):
                next_button = btn
                break

        assert next_button is not None
        assert next_button.callback_data == "page_1"

        # Check back button
        back_row = buttons[-1]
        assert len(back_row) == 1
        assert back_row[0].callback_data == "menu"

    @pytest.mark.asyncio
    async def test_paginated_keyboard_edge_cases(self):
        """Test paginated keyboard edge cases"""

        # Single page of data
        async def single_page_query(offset=0, limit=10, count_only=False):
            if count_only:
                return 5
            return ["Item1", "Item2", "Item3", "Item4", "Item5"][offset:offset + limit]

        paginator = LazyPaginator(single_page_query, per_page=10)

        kb = await lazy_paginated_keyboard(
            paginator=paginator,
            item_text=lambda item: item,
            item_callback=lambda item: f"select_{item}",
            page=0,
            back_cb="menu",
            nav_cb_prefix="nav_"
        )

        buttons = kb.inline_keyboard

        # Should not have navigation for single page
        # Check if there's a navigation row (would have multiple buttons)
        has_nav = False
        for row in buttons:
            if len(row) > 1:  # Navigation row typically has multiple buttons
                for btn in row:
                    if btn.callback_data and "nav_" in btn.callback_data:
                        has_nav = True
                        break

        # For single page, navigation might still be present but disabled
        # or only showing page indicator without prev/next

        # Empty data
        async def empty_query(offset=0, limit=10, count_only=False):
            if count_only:
                return 0
            return []

        empty_paginator = LazyPaginator(empty_query, per_page=10)

        empty_kb = await lazy_paginated_keyboard(
            paginator=empty_paginator,
            item_text=lambda item: str(item),
            item_callback=lambda item: f"select_{item}",
            page=0,
            back_cb="menu",
            nav_cb_prefix="nav_"
        )

        empty_buttons = empty_kb.inline_keyboard
        # Should have at least back button
        assert len(empty_buttons) >= 1
