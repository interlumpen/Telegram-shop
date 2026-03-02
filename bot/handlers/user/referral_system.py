from functools import partial

from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext

from bot.database.methods import (
    check_user_referrals, get_referral_earnings_stats, get_one_referral_earning, query_user_referrals,
    query_referral_earnings_from_user, query_all_referral_earnings,
)
from bot.handlers.other import get_bot_info
from bot.keyboards import back, referral_system_keyboard, lazy_paginated_keyboard
from bot.misc import EnvKeys, LazyPaginator
from bot.i18n import localize

router = Router()


@router.callback_query(F.data == "referral_system")
async def referral_callback_handler(call: CallbackQuery, state: FSMContext):
    """
    Show referral info, personal invite link, and additional buttons.
    """
    user_id = call.from_user.id
    referrals_count = await check_user_referrals(user_id)
    referral_percent = EnvKeys.REFERRAL_PERCENT
    bot_username = await get_bot_info(call)

    earnings_stats = await get_referral_earnings_stats(user_id)

    has_referrals = referrals_count > 0
    has_earnings = earnings_stats['total_earnings_count'] > 0

    text = (
        f"{localize('referral.title')}\n"
        f"{localize('referral.link', bot_username=bot_username, user_id=user_id)}\n"
        f"{localize('referral.count', count=referrals_count)}\n"
        f"{localize('referral.description', percent=referral_percent)}"
    )

    if has_earnings:
        text += "\n\n" + localize('referrals.stats.template',
                                  active_count=earnings_stats['active_referrals_count'],
                                  total_earned=int(earnings_stats['total_amount']),
                                  total_original=int(earnings_stats['total_original_amount']),
                                  earnings_count=earnings_stats['total_earnings_count'],
                                  currency=EnvKeys.PAY_CURRENCY
                                  )

    markup = referral_system_keyboard(has_referrals, has_earnings)
    await call.message.edit_text(text, reply_markup=markup)
    await state.clear()


@router.callback_query(F.data == "view_referrals")
async def view_referrals_handler(call: CallbackQuery, state: FSMContext):
    """
    Show a list of all user referrals with lazy loading.
    """
    user_id = call.from_user.id

    # Create paginator
    query_func = partial(query_user_referrals, user_id)
    paginator = LazyPaginator(query_func, per_page=10)

    # Check if there are any referrals
    total = await paginator.get_total_count()
    if total == 0:
        await call.message.edit_text(
            localize("referrals.list.empty"),
            reply_markup=back("referral_system")
        )
        return

    markup = await lazy_paginated_keyboard(
        paginator=paginator,
        item_text=lambda referral_data: localize("referrals.item.format",
                                                 telegram_id=referral_data['telegram_id'],
                                                 total_earned=int(referral_data['total_earned']),
                                                 currency=EnvKeys.PAY_CURRENCY),
        item_callback=lambda referral_data: f"referral_earnings_{referral_data['telegram_id']}",
        page=0,
        back_cb="referral_system",
        nav_cb_prefix="referrals_page_"
    )

    await call.message.edit_text(
        localize("referrals.list.title"),
        reply_markup=markup
    )

    # Save state
    await state.update_data(referrals_paginator=paginator.get_state())


@router.callback_query(F.data.startswith("referrals_page_"))
async def referrals_pagination_handler(call: CallbackQuery, state: FSMContext):
    """
    Pagination processing for the referral list with lazy loading.
    """
    try:
        page = int(call.data.split("_")[-1])
    except (ValueError, IndexError):
        await call.answer(localize("errors.pagination_invalid"))
        return

    user_id = call.from_user.id

    # Get saved state
    data = await state.get_data()
    paginator_state = data.get('referrals_paginator')

    # Create paginator with cached state
    query_func = partial(query_user_referrals, user_id)
    paginator = LazyPaginator(query_func, per_page=10, state=paginator_state)

    markup = await lazy_paginated_keyboard(
        paginator=paginator,
        item_text=lambda referral_data: localize("referrals.item.format",
                                                 telegram_id=referral_data['telegram_id'],
                                                 total_earned=int(referral_data['total_earned']),
                                                 currency=EnvKeys.PAY_CURRENCY),
        item_callback=lambda referral_data: f"referral_earnings_{referral_data['telegram_id']}",
        page=page,
        back_cb="referral_system",
        nav_cb_prefix="referrals_page_"
    )

    await call.message.edit_text(
        localize("referrals.list.title"),
        reply_markup=markup
    )

    # Update state
    await state.update_data(referrals_paginator=paginator.get_state())


@router.callback_query(F.data.startswith("referral_earnings_"))
async def referral_earnings_handler(call: CallbackQuery, state: FSMContext):
    """
    Show all earnings from a specific referral with lazy loading.
    """
    try:
        referral_id = int(call.data.split("_")[-1])
    except (ValueError, IndexError):
        await call.answer(localize("errors.invalid_data"))
        return

    user_id = call.from_user.id

    # Create paginator
    query_func = partial(query_referral_earnings_from_user, user_id, referral_id)
    paginator = LazyPaginator(query_func, per_page=10)

    # Check if there are any earnings
    total = await paginator.get_total_count()
    if total == 0:
        referral_info = await call.message.bot.get_chat(referral_id)
        await call.message.edit_text(
            localize("referral.earnings.empty", id=referral_id, name=referral_info.first_name),
            reply_markup=back("view_referrals")
        )
        return

    markup = await lazy_paginated_keyboard(
        paginator=paginator,
        item_text=lambda earning: localize("referral.earning.format",
                                           amount=int(earning.amount),
                                           currency=EnvKeys.PAY_CURRENCY,
                                           date=earning.created_at.strftime("%d.%m.%Y %H:%M"),
                                           original_amount=int(earning.original_amount)),
        item_callback=lambda earning: f"earning_detail:{earning.id}:referral_earnings_{referral_id}",
        page=0,
        back_cb="view_referrals",
        nav_cb_prefix=f"ref_earnings_{referral_id}_page_"
    )

    referral_info = await call.message.bot.get_chat(referral_id)
    title_text = localize("referral.earnings.title", telegram_id=referral_id, name=referral_info.first_name)
    await call.message.edit_text(title_text, reply_markup=markup)

    # Save state
    await state.update_data(ref_earnings_paginator=paginator.get_state())


@router.callback_query(F.data == "view_all_earnings")
async def view_all_earnings_handler(call: CallbackQuery, state: FSMContext):
    """
    Show all user referral earnings with lazy loading.
    """
    user_id = call.from_user.id

    # Create paginator
    query_func = partial(query_all_referral_earnings, user_id)
    paginator = LazyPaginator(query_func, per_page=10)

    # Check if there are any earnings
    total = await paginator.get_total_count()
    if total == 0:
        await call.message.edit_text(
            localize("all.earnings.empty"),
            reply_markup=back("referral_system")
        )
        return

    markup = await lazy_paginated_keyboard(
        paginator=paginator,
        item_text=lambda earning: localize("all.earning.format",
                                           amount=int(earning.amount),
                                           currency=EnvKeys.PAY_CURRENCY,
                                           referral_id=earning.referral_id,
                                           date=earning.created_at.strftime("%d.%m.%Y %H:%M")),
        item_callback=lambda earning: f"earning_detail:{earning.id}:view_all_earnings",
        page=0,
        back_cb="referral_system",
        nav_cb_prefix="all_earnings_page_"
    )

    await call.message.edit_text(
        localize("all.earnings.title"),
        reply_markup=markup
    )

    # Save state
    await state.update_data(all_earnings_paginator=paginator.get_state())


@router.callback_query(F.data.startswith("all_earnings_page_"))
async def all_earnings_pagination_handler(call: CallbackQuery, state: FSMContext):
    """
    Pagination processing for all referral earnings with lazy loading.
    """
    try:
        page = int(call.data.split("_")[-1])
    except (ValueError, IndexError):
        await call.answer(localize("errors.pagination_invalid"))
        return

    user_id = call.from_user.id

    # Get saved state
    data = await state.get_data()
    paginator_state = data.get('all_earnings_paginator')

    # Create paginator with cached state
    query_func = partial(query_all_referral_earnings, user_id)
    paginator = LazyPaginator(query_func, per_page=10, state=paginator_state)

    markup = await lazy_paginated_keyboard(
        paginator=paginator,
        item_text=lambda earning: localize("all.earning.format",
                                           amount=int(earning.amount),
                                           currency=EnvKeys.PAY_CURRENCY,
                                           referral_id=earning.referral_id,
                                           date=earning.created_at.strftime("%d.%m.%Y %H:%M")),
        item_callback=lambda earning: f"earning_detail:{earning.id}:all_earnings_page_{page}",
        page=page,
        back_cb="referral_system",
        nav_cb_prefix="all_earnings_page_"
    )

    await call.message.edit_text(
        localize("all.earnings.title"),
        reply_markup=markup
    )

    # Update state
    await state.update_data(all_earnings_paginator=paginator.get_state())


@router.callback_query(F.data.startswith("earning_detail:"))
async def referral_callback_handler(call: CallbackQuery, state: FSMContext):
    """
    Show referral info, personal invite link, and additional buttons.
    """
    trash, earning_id, back_data = call.data.split(':', 2)
    earning_info = await get_one_referral_earning(int(earning_id))
    user_info = await call.message.bot.get_chat(earning_info['referral_id'])

    await call.message.edit_text(localize('referral.item.info',
                                          id=earning_id,
                                          telegram_id=earning_info['referral_id'],
                                          name=user_info.first_name,
                                          amount=earning_info['amount'],
                                          currency=EnvKeys.PAY_CURRENCY,
                                          date=earning_info['created_at'].strftime("%d.%m.%Y %H:%M"),
                                          original_amount=earning_info['original_amount']
                                          ), reply_markup=back(back_data))
    await state.clear()
