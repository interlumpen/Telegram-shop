from decimal import Decimal
from functools import partial

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from bot.i18n import localize
from bot.database.models import Permission
from bot.database.methods import (
    select_user_operations, select_user_items, check_role_name_by_id, check_user_referrals, set_role, check_user_cached,
    create_operation, update_balance, get_role_id_by_name, get_referral_earnings_stats, get_one_referral_earning,
    query_user_bought_items, query_user_referrals, query_referral_earnings_from_user, query_all_referral_earnings,
    is_user_blocked
)
from bot.keyboards import back, close, simple_buttons, lazy_paginated_keyboard
from bot.logger_mesh import audit_logger
from bot.filters import HasPermissionFilter
from bot.states import UserMgmtStates

import datetime

from bot.misc import EnvKeys, LazyPaginator, validate_telegram_id, validate_money_amount, UserDataUpdate

router = Router()


@router.callback_query(F.data == 'user_management', HasPermissionFilter(Permission.USERS_MANAGE))
async def user_callback_handler(call: CallbackQuery, state: FSMContext):
    """
    Asks admin to enter a user's ID to view / modify.
    """
    await state.clear()
    await call.message.edit_text(
        localize('admin.users.prompt_enter_id'),
        reply_markup=back('console')
    )
    await state.set_state(UserMgmtStates.waiting_user_id_for_check)


@router.message(UserMgmtStates.waiting_user_id_for_check, F.text)
async def check_user_data(message: Message, state: FSMContext):
    """Validates ID and shows user profile directly."""
    try:
        # Validate user ID
        target_id = validate_telegram_id(message.text.strip())

        user = await check_user_cached(target_id)
        if not user:
            await message.answer(
                localize('admin.users.profile_unavailable'),
                reply_markup=back('console')
            )
            return

        # Get user profile data
        user_info = await message.bot.get_chat(target_id)
        operations = select_user_operations(target_id)
        overall_balance = sum(operations) if operations else 0
        items_count = select_user_items(target_id)
        role = check_role_name_by_id(user.get('role_id'))
        referrals = check_user_referrals(user.get('telegram_id'))

        # Get referral earnings stats for the user
        earnings_stats = get_referral_earnings_stats(target_id)
        has_referrals = referrals > 0
        has_earnings = earnings_stats['total_earnings_count'] > 0

        # Action buttons
        actions: list[tuple[str, str]] = []
        role_name = role  # 'USER' | 'ADMIN' | 'OWNER'

        if role_name == 'OWNER':
            # Do nothing: owner's role is immutable for safety
            pass
        elif role_name == 'ADMIN':
            actions.append((localize('btn.admin.demote'), f"remove-admin_{target_id}"))
        else:  # USER
            actions.append((localize('btn.admin.promote'), f"set-admin_{target_id}"))

        actions.append((localize('btn.admin.replenish_user'), f"fill-user-balance_{target_id}"))

        # Block/unblock button (not for OWNER)
        if role_name != 'OWNER':
            if is_user_blocked(target_id):
                actions.append((localize('btn.admin.unblock'), f"unblock-user_{target_id}"))
            else:
                actions.append((localize('btn.admin.block'), f"block-user_{target_id}"))

        if items_count:
            actions.append((localize('btn.purchased'), f"user-items_{target_id}"))

        # Add referral-related buttons
        if has_referrals:
            actions.append((localize('admin.users.btn.view_referrals'), f"admin-view-referrals_{target_id}"))

        if has_earnings:
            actions.append((localize('admin.users.btn.view_earnings'), f"admin-view-earnings_{target_id}"))

        actions.append((localize('btn.back'), "user_management"))

        markup = simple_buttons(actions, per_row=1)

        lines = [
            localize('profile.caption', name=user_info.first_name, id=target_id),
            '',
            localize('profile.id', id=target_id),
            localize('profile.balance', amount=user.get('balance'), currency=EnvKeys.PAY_CURRENCY),
            localize('profile.total_topup', amount=overall_balance, currency=EnvKeys.PAY_CURRENCY),
            localize('profile.purchased_count', count=items_count),
            '',
            localize('admin.users.referrals', count=referrals),
            localize('admin.users.role', role=role),
            localize('profile.registration_date', dt=user.get('registration_date')),
        ]

        # Add referral earnings stats if available
        if has_earnings:
            lines.append('')
            lines.append(localize('referrals.stats.template',
                                  active_count=earnings_stats['active_referrals_count'],
                                  total_earned=int(earnings_stats['total_amount']),
                                  total_original=int(earnings_stats['total_original_amount']),
                                  earnings_count=earnings_stats['total_earnings_count'],
                                  currency=EnvKeys.PAY_CURRENCY))

        await message.answer(
            '\n'.join(lines),
            parse_mode='HTML',
            reply_markup=markup
        )
        await state.clear()
    except ValueError as e:
        await message.answer(
            localize('admin.users.invalid_id'),
            reply_markup=back('console')
        )
        return


@router.callback_query(F.data.startswith('check-user_'), HasPermissionFilter(Permission.USERS_MANAGE))
async def user_profile_view(call: CallbackQuery):
    """
    Shows admin view of user profile + actions.
    """
    user_id_str = call.data[len('check-user_'):]
    try:
        target_id = int(user_id_str)
    except (ValueError, TypeError):
        await call.answer(localize('errors.invalid_data'), show_alert=True)
        return

    user = await check_user_cached(target_id)
    if not user:
        await call.answer(localize('admin.users.not_found'), show_alert=True)
        return

    user_info = await call.message.bot.get_chat(target_id)

    operations = select_user_operations(target_id)
    overall_balance = sum(operations) if operations else 0
    items_count = select_user_items(target_id)
    role = check_role_name_by_id(user.get('role_id'))
    referrals = check_user_referrals(user.get('telegram_id'))

    # Get referral earnings stats for the user
    earnings_stats = get_referral_earnings_stats(target_id)
    has_referrals = referrals > 0
    has_earnings = earnings_stats['total_earnings_count'] > 0

    # Action buttons
    actions: list[tuple[str, str]] = []
    role_name = role  # 'USER' | 'ADMIN' | 'OWNER'

    if role_name == 'OWNER':
        # Do nothing: owner's role is immutable for safety
        pass
    elif role_name == 'ADMIN':
        actions.append((localize('btn.admin.demote'), f"remove-admin_{target_id}"))
    else:  # USER
        actions.append((localize('btn.admin.promote'), f"set-admin_{target_id}"))

    actions.append((localize('btn.admin.replenish_user'), f"fill-user-balance_{target_id}"))

    # Block/unblock button (not for OWNER)
    if role_name != 'OWNER':
        if is_user_blocked(target_id):
            actions.append((localize('btn.admin.unblock'), f"unblock-user_{target_id}"))
        else:
            actions.append((localize('btn.admin.block'), f"block-user_{target_id}"))

    if items_count:
        actions.append((localize('btn.purchased'), f"user-items_{target_id}"))

    # Add referral-related buttons
    if has_referrals:
        actions.append((localize('admin.users.btn.view_referrals'), f"admin-view-referrals_{target_id}"))

    if has_earnings:
        actions.append((localize('admin.users.btn.view_earnings'), f"admin-view-earnings_{target_id}"))

    actions.append((localize('btn.back'), "user_management"))

    markup = simple_buttons(actions, per_row=1)

    # Check if user is blocked for status display
    user_blocked = is_user_blocked(target_id)

    lines = [
        localize('profile.caption', name=user_info.first_name, id=target_id),
        '',
        localize('profile.id', id=target_id),
        localize('profile.balance', amount=user.get('balance'), currency=EnvKeys.PAY_CURRENCY),
        localize('profile.total_topup', amount=overall_balance, currency=EnvKeys.PAY_CURRENCY),
        localize('profile.purchased_count', count=items_count),
        '',
        localize('admin.users.referrals', count=referrals),
        localize('admin.users.role', role=role),
        localize('profile.registration_date', dt=user.get('registration_date')),
    ]

    # Add blocked status if blocked
    if user_blocked:
        lines.append(localize('admin.users.status.blocked'))

    # Add referral earnings stats if available
    if has_earnings:
        lines.append('')
        lines.append(localize('referrals.stats.template',
                              active_count=earnings_stats['active_referrals_count'],
                              total_earned=int(earnings_stats['total_amount']),
                              total_original=int(earnings_stats['total_original_amount']),
                              earnings_count=earnings_stats['total_earnings_count'],
                              currency=EnvKeys.PAY_CURRENCY))

    await call.message.edit_text(
        '\n'.join(lines),
        parse_mode='HTML',
        reply_markup=markup
    )


@router.callback_query(F.data.startswith('admin-view-referrals_'), HasPermissionFilter(Permission.USERS_MANAGE))
async def admin_view_referrals_handler(call: CallbackQuery, state: FSMContext):
    """
    Show a list of all referrals for selected user with lazy loading (admin view).
    """
    try:
        user_id = int(call.data.split('_')[-1])
    except (ValueError, IndexError):
        await call.answer(localize('errors.invalid_data'))
        return

    # Create paginator
    query_func = partial(query_user_referrals, user_id)
    paginator = LazyPaginator(query_func, per_page=10)

    # Check if there are any referrals
    total = await paginator.get_total_count()
    if total == 0:
        await call.message.edit_text(
            localize("referrals.list.empty"),
            reply_markup=back(f"check-user_{user_id}")
        )
        return

    markup = await lazy_paginated_keyboard(
        paginator=paginator,
        item_text=lambda referral_data: localize("referrals.item.format",
                                                 telegram_id=referral_data['telegram_id'],
                                                 total_earned=int(referral_data['total_earned']),
                                                 currency=EnvKeys.PAY_CURRENCY),
        item_callback=lambda referral_data: f"admin-ref-earnings_{user_id}_{referral_data['telegram_id']}",
        page=0,
        back_cb=f"check-user_{user_id}",
        nav_cb_prefix=f"admin-refs-page_{user_id}_"
    )

    user_info = await call.message.bot.get_chat(user_id)
    await call.message.edit_text(
        localize(
            "referrals.list.title") + f"\n(<a href='tg://user?id={user_id}'>{user_info.first_name}</a> - {user_id})",
        reply_markup=markup
    )

    # Save state
    await state.update_data(admin_referrals_paginator=paginator.get_state())


@router.callback_query(F.data.startswith("admin-refs-page_"), HasPermissionFilter(Permission.USERS_MANAGE))
async def admin_referrals_pagination_handler(call: CallbackQuery, state: FSMContext):
    """
    Pagination processing for the referral list with lazy loading (admin view).
    """
    try:
        parts = call.data.split("_")
        user_id = int(parts[1])
        page = int(parts[2])
    except (ValueError, IndexError):
        await call.answer(localize("errors.pagination_invalid"))
        return

    # Get saved state
    data = await state.get_data()
    paginator_state = data.get('admin_referrals_paginator')

    # Create paginator with cached state
    query_func = partial(query_user_referrals, user_id)
    paginator = LazyPaginator(query_func, per_page=10, state=paginator_state)

    markup = await lazy_paginated_keyboard(
        paginator=paginator,
        item_text=lambda referral_data: localize("referrals.item.format",
                                                 telegram_id=referral_data['telegram_id'],
                                                 total_earned=int(referral_data['total_earned']),
                                                 currency=EnvKeys.PAY_CURRENCY),
        item_callback=lambda referral_data: f"admin-ref-earnings_{user_id}_{referral_data['telegram_id']}",
        page=page,
        back_cb=f"check-user_{user_id}",
        nav_cb_prefix=f"admin-refs-page_{user_id}_"
    )

    user_info = await call.message.bot.get_chat(user_id)
    await call.message.edit_text(
        localize(
            "referrals.list.title") + f"\n(<a href='tg://user?id={user_id}'>{user_info.first_name}</a> - {user_id})",
        reply_markup=markup
    )

    # Update state
    await state.update_data(admin_referrals_paginator=paginator.get_state())


@router.callback_query(F.data.startswith("admin-ref-earnings_"), HasPermissionFilter(Permission.USERS_MANAGE))
async def admin_referral_earnings_handler(call: CallbackQuery, state: FSMContext):
    """
    Show all earnings from a specific referral for selected user with lazy loading (admin view).
    """
    try:
        parts = call.data.split("_")
        user_id = int(parts[1])
        referral_id = int(parts[2])
    except (ValueError, IndexError):
        await call.answer(localize("errors.invalid_data"))
        return

    # Create paginator
    query_func = partial(query_referral_earnings_from_user, user_id, referral_id)
    paginator = LazyPaginator(query_func, per_page=10)

    # Check if there are any earnings
    total = await paginator.get_total_count()
    if total == 0:
        referral_info = await call.message.bot.get_chat(referral_id)
        await call.message.edit_text(
            localize("referral.earnings.empty", id=referral_id, name=referral_info.first_name),
            reply_markup=back(f"admin-view-referrals_{user_id}")
        )
        return

    markup = await lazy_paginated_keyboard(
        paginator=paginator,
        item_text=lambda earning: localize("referral.earning.format",
                                           amount=int(earning.amount),
                                           currency=EnvKeys.PAY_CURRENCY,
                                           date=earning.created_at.strftime("%d.%m.%Y %H:%M"),
                                           original_amount=int(earning.original_amount)),
        item_callback=lambda earning: f"admin-earning-detail:{earning.id}:admin-ref-earnings_{user_id}_{referral_id}",
        page=0,
        back_cb=f"admin-view-referrals_{user_id}",
        nav_cb_prefix=f"admin-ref-earn_{user_id}_{referral_id}_page_"
    )

    referral_info = await call.message.bot.get_chat(referral_id)
    title_text = localize("referral.earnings.title", telegram_id=referral_id, name=referral_info.first_name)
    await call.message.edit_text(title_text, reply_markup=markup)

    # Save state
    await state.update_data(admin_ref_earnings_paginator=paginator.get_state())


@router.callback_query(F.data.startswith('admin-view-earnings_'), HasPermissionFilter(Permission.USERS_MANAGE))
async def admin_view_all_earnings_handler(call: CallbackQuery, state: FSMContext):
    """
    Show all referral earnings for selected user with lazy loading (admin view).
    """
    try:
        user_id = int(call.data.split('_')[-1])
    except (ValueError, IndexError):
        await call.answer(localize('errors.invalid_data'))
        return

    # Create paginator
    query_func = partial(query_all_referral_earnings, user_id)
    paginator = LazyPaginator(query_func, per_page=10)

    # Check if there are any earnings
    total = await paginator.get_total_count()
    if total == 0:
        await call.message.edit_text(
            localize("all.earnings.empty"),
            reply_markup=back(f"check-user_{user_id}")
        )
        return

    markup = await lazy_paginated_keyboard(
        paginator=paginator,
        item_text=lambda earning: localize("all.earning.format",
                                           amount=int(earning.amount),
                                           currency=EnvKeys.PAY_CURRENCY,
                                           referral_id=earning.referral_id,
                                           date=earning.created_at.strftime("%d.%m.%Y %H:%M")),
        item_callback=lambda earning: f"admin-earning-detail:{earning.id}:admin-view-earnings_{user_id}",
        page=0,
        back_cb=f"check-user_{user_id}",
        nav_cb_prefix=f"admin-all-earn_{user_id}_page_"
    )

    user_info = await call.message.bot.get_chat(user_id)
    await call.message.edit_text(
        localize("all.earnings.title") + f"\n(<a href='tg://user?id={user_id}'>{user_info.first_name}</a> - {user_id})",
        reply_markup=markup
    )

    # Save state
    await state.update_data(admin_all_earnings_paginator=paginator.get_state())


@router.callback_query(F.data.startswith("admin-all-earn_"), HasPermissionFilter(Permission.USERS_MANAGE))
async def admin_all_earnings_pagination_handler(call: CallbackQuery, state: FSMContext):
    """
    Pagination processing for all referral earnings with lazy loading (admin view).
    """
    try:
        parts = call.data.split("_")
        user_id = int(parts[1])
        page = int(parts[3])
    except (ValueError, IndexError):
        await call.answer(localize("errors.pagination_invalid"))
        return

    # Get saved state
    data = await state.get_data()
    paginator_state = data.get('admin_all_earnings_paginator')

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
        item_callback=lambda earning: f"admin-earning-detail:{earning.id}:admin-all-earn_{user_id}_page_{page}",
        page=page,
        back_cb=f"check-user_{user_id}",
        nav_cb_prefix=f"admin-all-earn_{user_id}_page_"
    )

    user_info = await call.message.bot.get_chat(user_id)
    await call.message.edit_text(
        localize("all.earnings.title") + f"\n(<a href='tg://user?id={user_id}'>{user_info.first_name}</a> - {user_id})",
        reply_markup=markup
    )

    # Update state
    await state.update_data(admin_all_earnings_paginator=paginator.get_state())


@router.callback_query(F.data.startswith("admin-earning-detail:"), HasPermissionFilter(Permission.USERS_MANAGE))
async def admin_earning_detail_handler(call: CallbackQuery):
    """
    Show detailed information about specific earning (admin view).
    """
    try:
        parts = call.data.split(':', 2)
        earning_id = int(parts[1])
        back_data = parts[2]
    except (ValueError, IndexError):
        await call.answer(localize('errors.invalid_data'))
        return

    earning_info = get_one_referral_earning(earning_id)
    if not earning_info:
        await call.answer(localize('errors.invalid_data'))
        return

    referral_info = await call.message.bot.get_chat(earning_info['referral_id'])

    await call.message.edit_text(
        localize('referral.item.info',
                 id=earning_id,
                 telegram_id=earning_info['referral_id'],
                 name=referral_info.first_name,
                 amount=earning_info['amount'],
                 currency=EnvKeys.PAY_CURRENCY,
                 date=earning_info['created_at'].strftime("%d.%m.%Y %H:%M"),
                 original_amount=earning_info['original_amount']),
        reply_markup=back(back_data)
    )


@router.callback_query(F.data.startswith('user-items_'), HasPermissionFilter(Permission.USERS_MANAGE))
async def user_items_callback_handler(call: CallbackQuery, state: FSMContext):
    """
    Shows bought items of a specific user with lazy loading.
    Callback data format: user-items_{user_id}
    """
    try:
        user_id = int(call.data[len('user-items_'):])
    except (ValueError, TypeError):
        await call.answer(localize('errors.invalid_data'), show_alert=True)
        return

    # Create paginator
    query_func = partial(query_user_bought_items, user_id)
    paginator = LazyPaginator(query_func, per_page=10)

    markup = await lazy_paginated_keyboard(
        paginator=paginator,
        item_text=lambda item: item.item_name,
        item_callback=lambda item: f"bought-item:{item.id}:bought-goods-page_{user_id}_0",
        page=0,
        back_cb=f'check-user_{user_id}',
        nav_cb_prefix=f"bought-goods-page_{user_id}_"
    )

    await call.message.edit_text(localize('purchases.title'), reply_markup=markup)

    # Save state for admin viewing user's items
    await state.update_data(admin_user_items_paginator=paginator.get_state())


@router.callback_query(F.data.startswith('set-admin_'), HasPermissionFilter(Permission.ADMINS_MANAGE))
async def process_admin_for_purpose(call: CallbackQuery):
    """
    Assigns ADMIN role to the user.
    """
    user_data = call.data[len('set-admin_'):]
    try:
        user_id = int(user_data)
    except (ValueError, TypeError):
        await call.answer(localize('errors.invalid_data'), show_alert=True)
        return

    db_user = await check_user_cached(user_id)
    if not db_user:
        await call.answer(localize('admin.users.not_found'), show_alert=True)
        return

    role_name = check_role_name_by_id(db_user.get('role_id'))
    if role_name == 'OWNER':
        await call.answer(localize('admin.users.cannot_change_owner'), show_alert=True)
        return

    admin_role_id = get_role_id_by_name('ADMIN')
    set_role(user_id, admin_role_id)

    user_info = await call.message.bot.get_chat(user_id)
    await call.message.edit_text(
        localize('admin.users.set_admin.success', name=user_info.first_name),
        reply_markup=back(f'check-user_{user_id}')
    )
    try:
        await call.message.bot.send_message(
            chat_id=user_id,
            text=localize('admin.users.set_admin.notify'),
            reply_markup=close()
        )
    except (TelegramBadRequest, TelegramForbiddenError) as e:
        audit_logger.error(f"Failed to notify user {user_id} about admin role assignment: {e}")

    admin_info = await call.message.bot.get_chat(call.from_user.id)
    audit_logger.info(
        f"User {call.from_user.id} ({admin_info.first_name}) assigned user"
        f"{user_id} ({user_info.first_name}) as administrator"
    )


@router.callback_query(F.data.startswith('remove-admin_'), HasPermissionFilter(Permission.ADMINS_MANAGE))
async def process_admin_for_remove(call: CallbackQuery):
    """
    Revokes ADMIN role from the user (sets USER).
    """
    user_data = call.data[len('remove-admin_'):]
    try:
        user_id = int(user_data)
    except (ValueError, TypeError):
        await call.answer(localize('errors.invalid_data'), show_alert=True)
        return

    db_user = await check_user_cached(user_id)
    if not db_user:
        await call.answer(localize('admin.users.not_found'), show_alert=True)
        return

    role_name = check_role_name_by_id(db_user.get('role_id'))
    if role_name == 'OWNER':
        await call.answer(localize('admin.users.cannot_change_owner'), show_alert=True)
        return

    user_role_id = get_role_id_by_name('USER')
    set_role(user_id, user_role_id)

    user_info = await call.message.bot.get_chat(user_id)
    await call.message.edit_text(
        localize('admin.users.remove_admin.success', name=user_info.first_name),
        reply_markup=back(f'check-user_{user_id}')
    )
    try:
        await call.message.bot.send_message(
            chat_id=user_id,
            text=localize('admin.users.remove_admin.notify'),
            reply_markup=close()
        )
    except (TelegramBadRequest, TelegramForbiddenError) as e:
        audit_logger.error(f"Failed to notify user {user_id} about admin role removal: {e}")

    admin_info = await call.message.bot.get_chat(call.from_user.id)
    audit_logger.info(
        f"User {call.from_user.id} ({admin_info.first_name}) revoked the role administrator"
        f" from the user {user_id} ({user_info.first_name})"
    )


@router.callback_query(F.data.startswith('fill-user-balance_'), HasPermissionFilter(Permission.USERS_MANAGE))
async def replenish_user_balance_callback_handler(call: CallbackQuery, state: FSMContext):
    """
    Asks for amount to top up selected user's balance.
    """
    user_data = call.data[len('fill-user-balance_'):]
    try:
        user_id = int(user_data)
    except (ValueError, TypeError):
        await call.answer(localize('errors.invalid_data'), show_alert=True)
        return

    await call.message.edit_text(
        localize('payments.replenish_prompt', currency=EnvKeys.PAY_CURRENCY),
        reply_markup=back(f'check-user_{user_id}')
    )
    await state.set_state(UserMgmtStates.waiting_user_replenish)
    await state.update_data(target_user=user_id)


@router.message(UserMgmtStates.waiting_user_replenish, F.text)
async def process_replenish_user_balance(message: Message, state: FSMContext):
    """Processes entered amount and tops up user's balance."""
    data = await state.get_data()
    user_id = data.get('target_user')

    try:
        # Validate amount
        amount = validate_money_amount(
            message.text.strip(),
            min_amount=Decimal(EnvKeys.MIN_AMOUNT),
            max_amount=Decimal(EnvKeys.MAX_AMOUNT)
        )

        # Validate user update
        user_update = UserDataUpdate(
            telegram_id=user_id,
            balance=amount
        )

        # Apply top-up
        create_operation(user_update.telegram_id, int(amount), datetime.datetime.now())
        update_balance(user_update.telegram_id, int(amount))

        user_info = await message.bot.get_chat(user_id)
        await message.answer(
            localize('admin.users.balance.topped',
                     name=user_info.first_name,
                     amount=int(amount),
                     currency=EnvKeys.PAY_CURRENCY),
            reply_markup=back(f'check-user_{user_id}')
        )

        # Audit logging
        admin_info = await message.bot.get_chat(message.from_user.id)
        audit_logger.info(
            f"User {message.from_user.id} ({admin_info.first_name}) topped up the balance of user "
            f"{user_id} ({user_info.first_name}) by {int(amount)}"
        )

        # Notify user
        try:
            await message.bot.send_message(
                chat_id=user_id,
                text=localize('admin.users.balance.topped.notify',
                              amount=int(amount),
                              currency=EnvKeys.PAY_CURRENCY),
                reply_markup=close()
            )
        except (TelegramBadRequest, TelegramForbiddenError) as e:
            audit_logger.error(f"Failed to notify user {user_id} about balance top-up: {e}")

        await state.clear()

    except ValueError as e:
        await message.answer(
            localize('payments.replenish_invalid',
                     min_amount=EnvKeys.MIN_AMOUNT,
                     max_amount=EnvKeys.MAX_AMOUNT,
                     currency=EnvKeys.PAY_CURRENCY),
            reply_markup=back(f'check-user_{user_id}')
        )


@router.callback_query(F.data.startswith('check-user_'), HasPermissionFilter(permission=Permission.USERS_MANAGE))
async def check_user_profile_again(call: CallbackQuery):
    """
    Re-uses user_profile_view to show the profile again.
    """
    await user_profile_view(call)


@router.callback_query(F.data.startswith('block-user_'), HasPermissionFilter(Permission.USERS_MANAGE))
async def block_user_handler(call: CallbackQuery):
    """
    Block a user from using the bot.
    """
    user_id_str = call.data[len('block-user_'):]
    try:
        user_id = int(user_id_str)
    except (ValueError, TypeError):
        await call.answer(localize('errors.invalid_data'), show_alert=True)
        return

    db_user = await check_user_cached(user_id)
    if not db_user:
        await call.answer(localize('admin.users.not_found'), show_alert=True)
        return

    role_name = check_role_name_by_id(db_user.get('role_id'))
    if role_name == 'OWNER':
        await call.answer(localize('admin.users.cannot_block_owner'), show_alert=True)
        return

    from bot.main import auth_middleware
    if auth_middleware:
        success = auth_middleware.block_user(user_id)
        if not success:
            await call.answer(localize('errors.something_wrong'), show_alert=True)
            return

    user_info = await call.message.bot.get_chat(user_id)
    await call.message.edit_text(
        localize('admin.users.blocked.success', name=user_info.first_name),
        reply_markup=back(f'check-user_{user_id}')
    )

    admin_info = await call.message.bot.get_chat(call.from_user.id)
    audit_logger.info(
        f"Admin {call.from_user.id} ({admin_info.first_name}) blocked user "
        f"{user_id} ({user_info.first_name})"
    )


@router.callback_query(F.data.startswith('unblock-user_'), HasPermissionFilter(Permission.USERS_MANAGE))
async def unblock_user_handler(call: CallbackQuery):
    """
    Unblock a user.
    """
    user_id_str = call.data[len('unblock-user_'):]
    try:
        user_id = int(user_id_str)
    except (ValueError, TypeError):
        await call.answer(localize('errors.invalid_data'), show_alert=True)
        return

    from bot.main import auth_middleware
    if auth_middleware:
        success = auth_middleware.unblock_user(user_id)
        if not success:
            await call.answer(localize('errors.something_wrong'), show_alert=True)
            return

    user_info = await call.message.bot.get_chat(user_id)
    await call.message.edit_text(
        localize('admin.users.unblocked.success', name=user_info.first_name),
        reply_markup=back(f'check-user_{user_id}')
    )

    admin_info = await call.message.bot.get_chat(call.from_user.id)
    audit_logger.info(
        f"Admin {call.from_user.id} ({admin_info.first_name}) unblocked user "
        f"{user_id} ({user_info.first_name})"
    )
