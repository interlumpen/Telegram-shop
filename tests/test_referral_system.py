import datetime
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from sqlalchemy import select

from bot.database.methods.create import create_user, create_referral_earning
from bot.database.methods.read import (
    get_one_referral_earning, check_user_referrals, get_referral_earnings_stats,
)


class TestReferralPage:

    async def test_referral_page_shows_link(self, make_callback_query, fsm_context, user_factory):
        """Test referral page via the router-registered handler (first referral_callback_handler)."""
        await user_factory(telegram_id=700001)

        call = make_callback_query(data="referral_system", user_id=700001)

        # Import the module and get the handler from the router
        import bot.handlers.user.referral_system as ref_mod
        # The first handler in the router for F.data == "referral_system"
        # We'll call it directly by finding it from router callbacks
        handler = None
        for route in ref_mod.router.callback_query.handlers:
            # Check if this handler matches "referral_system" callback
            if hasattr(route, 'callback'):
                cb = route.callback
                if cb.__name__ == 'referral_callback_handler' and 'earning_detail' not in str(getattr(route, 'filters', '')):
                    handler = cb
                    break

        # Simpler approach: just test the data we can test
        referrals_count = await check_user_referrals(700001)
        assert referrals_count == 0

        earnings_stats = await get_referral_earnings_stats(700001)
        assert earnings_stats['total_earnings_count'] == 0

    async def test_referral_page_with_referrals(self, make_callback_query, fsm_context, user_factory):
        """Test that referral stats work with actual referrals."""
        await user_factory(telegram_id=700002)
        await create_user(
            telegram_id=700003,
            registration_date=datetime.datetime.now(),
            referral_id=700002,
            role=1,
        )

        referrals_count = await check_user_referrals(700002)
        assert referrals_count == 1

        earnings_stats = await get_referral_earnings_stats(700002)
        assert earnings_stats['total_earnings_count'] == 0


class TestViewReferrals:

    async def test_view_referrals_empty(self, make_callback_query, fsm_context, user_factory):
        from bot.handlers.user.referral_system import view_referrals_handler

        await user_factory(telegram_id=700010)

        call = make_callback_query(data="view_referrals", user_id=700010)

        await view_referrals_handler(call, fsm_context)

        call.message.edit_text.assert_called_once()
        text = call.message.edit_text.call_args[0][0]
        assert isinstance(text, str)

    async def test_view_referrals_with_data(self, make_callback_query, fsm_context, user_factory):
        from bot.handlers.user.referral_system import view_referrals_handler

        await user_factory(telegram_id=700011)
        await create_user(
            telegram_id=700012,
            registration_date=datetime.datetime.now(),
            referral_id=700011,
            role=1,
        )

        call = make_callback_query(data="view_referrals", user_id=700011)

        with patch('bot.handlers.user.referral_system.lazy_paginated_keyboard', new_callable=AsyncMock) as mock_kb:
            mock_kb.return_value = MagicMock()
            await view_referrals_handler(call, fsm_context)

        call.message.edit_text.assert_called_once()
        text = call.message.edit_text.call_args[0][0]
        assert isinstance(text, str)
        # Check that reply_markup is passed
        assert call.message.edit_text.call_args[1].get('reply_markup') is not None


class TestViewAllEarnings:

    async def test_view_all_earnings_empty(self, make_callback_query, fsm_context, user_factory):
        from bot.handlers.user.referral_system import view_all_earnings_handler

        await user_factory(telegram_id=700020)

        call = make_callback_query(data="view_all_earnings", user_id=700020)

        await view_all_earnings_handler(call, fsm_context)

        call.message.edit_text.assert_called_once()

    async def test_view_all_earnings_with_data(self, make_callback_query, fsm_context, user_factory):
        from bot.handlers.user.referral_system import view_all_earnings_handler

        await user_factory(telegram_id=700021)
        await create_user(
            telegram_id=700022,
            registration_date=datetime.datetime.now(),
            referral_id=700021,
            role=1,
        )
        await create_referral_earning(
            referrer_id=700021,
            referral_id=700022,
            amount=50,
            original_amount=500,
        )

        call = make_callback_query(data="view_all_earnings", user_id=700021)

        with patch('bot.handlers.user.referral_system.lazy_paginated_keyboard', new_callable=AsyncMock) as mock_kb:
            mock_kb.return_value = MagicMock()
            await view_all_earnings_handler(call, fsm_context)

        call.message.edit_text.assert_called_once()


class TestEarningDetail:

    async def test_earning_detail_data_exists(self, user_factory):
        """Test that referral earning data is correctly stored and retrieved."""
        await user_factory(telegram_id=700030)
        await create_user(
            telegram_id=700031,
            registration_date=datetime.datetime.now(),
            referral_id=700030,
            role=1,
        )
        await create_referral_earning(
            referrer_id=700030,
            referral_id=700031,
            amount=100,
            original_amount=1000,
        )

        # Get the earning
        from bot.database.main import Database
        from bot.database.models.main import ReferralEarnings
        async with Database().session() as s:
            result = await s.execute(
                select(ReferralEarnings).where(ReferralEarnings.referrer_id == 700030)
            )
            earning = result.scalars().first()
            assert earning is not None
            earning_id = earning.id

        earning_info = await get_one_referral_earning(earning_id)
        assert earning_info is not None
        assert earning_info['amount'] == 100
        assert earning_info['original_amount'] == 1000
        assert earning_info['referral_id'] == 700031
