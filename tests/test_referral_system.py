import datetime
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from sqlalchemy import select

import bot.handlers.user.referral_system as ref_mod
from bot.database.main import Database
from bot.database.methods.create import create_user
from tests.factories import add_referral_earning
from bot.database.methods.read import (
    get_one_referral_earning, check_user_referrals, get_referral_earnings_stats,
)
from bot.database.models.main import ReferralEarnings
from bot.handlers.user.referral_system import (
    view_referrals_handler, view_all_earnings_handler,
)


class TestReferralPage:

    async def test_referral_page_shows_link(self, user_factory):
        """A fresh user has no referrals and no earnings yet."""
        await user_factory(telegram_id=700001)

        assert await check_user_referrals(700001) == 0
        assert (await get_referral_earnings_stats(700001))['total_earnings_count'] == 0

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

        await user_factory(telegram_id=700010)

        call = make_callback_query(data="view_referrals", user_id=700010)

        await view_referrals_handler(call, fsm_context)

        call.message.edit_text.assert_called_once()
        assert "referrals.list.empty" in call.message.edit_text.call_args[0][0]

    async def test_view_referrals_with_data(self, make_callback_query, fsm_context, user_factory):

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
        assert "referrals.list.title" in call.message.edit_text.call_args[0][0]
        assert call.message.edit_text.call_args[1].get('reply_markup') is not None


class TestViewAllEarnings:

    async def test_view_all_earnings_empty(self, make_callback_query, fsm_context, user_factory):

        await user_factory(telegram_id=700020)

        call = make_callback_query(data="view_all_earnings", user_id=700020)

        await view_all_earnings_handler(call, fsm_context)

        call.message.edit_text.assert_called_once()
        assert "all.earnings.empty" in call.message.edit_text.call_args[0][0]

    async def test_view_all_earnings_with_data(self, make_callback_query, fsm_context, user_factory):

        await user_factory(telegram_id=700021)
        await create_user(
            telegram_id=700022,
            registration_date=datetime.datetime.now(),
            referral_id=700021,
            role=1,
        )
        await add_referral_earning(
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
        assert "all.earnings.title" in call.message.edit_text.call_args[0][0]
        assert call.message.edit_text.call_args[1].get('reply_markup') is not None


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
        await add_referral_earning(
            referrer_id=700030,
            referral_id=700031,
            amount=100,
            original_amount=1000,
        )

        # Get the earning
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
