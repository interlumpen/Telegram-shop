import asyncio
from typing import Optional

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.types import FSInputFile

from pathlib import Path
import datetime

from bot.database.models import Permission
from bot.database.methods import (
    select_today_users, select_admins, get_user_count, select_today_orders,
    select_all_orders, select_today_operations, select_users_balance, select_all_operations,
    select_count_items, select_count_goods, select_count_categories, select_count_bought_items,
    select_bought_item, check_user_referrals, check_role_name_by_id, select_user_items,
    select_user_operations, query_admins, query_all_users, check_user
)
from bot.keyboards import back, simple_buttons, lazy_paginated_keyboard
from bot.filters import HasPermissionFilter
from bot.logger_mesh import audit_logger
from bot.misc import EnvKeys, LazyPaginator, sanitize_html, SearchQuery, StatsCache, get_cache_manager
from bot.i18n import localize
from bot.states import GoodsFSM

router = Router()

# Initialize StatsCache as a global variable
stats_cache: Optional[StatsCache] = None


def init_stats_cache():
    """Initializing the statistics cache"""
    global stats_cache
    cache_manager = get_cache_manager()
    if cache_manager:
        stats_cache = StatsCache(cache_manager)
        asyncio.create_task(stats_cache.warm_up_cache())


@router.callback_query(F.data == "shop_management", HasPermissionFilter(Permission.SHOP_MANAGE))
async def shop_callback_handler(call: CallbackQuery):
    """
    Open shop-management main menu.
    """
    actions = [
        (localize("admin.shop.menu.statistics"), "statistics"),
        (localize("admin.shop.menu.logs"), "show_logs"),
        (localize("admin.shop.menu.admins"), "admins_list"),
        (localize("admin.shop.menu.users"), "users_list"),
        (localize("admin.shop.menu.search_bought"), "show_bought_item"),
        (localize("btn.back"), "console"),
    ]
    markup = simple_buttons(actions, per_row=1)
    await call.message.edit_text(localize("admin.shop.menu.title"), reply_markup=markup)


@router.callback_query(F.data == "show_logs", HasPermissionFilter(Permission.SHOP_MANAGE))
async def logs_callback_handler(call: CallbackQuery):
    """
    Send bot logs (audit) file if it exists and is not empty.
    """
    file_path = Path(EnvKeys.BOT_AUDITFILE)
    if file_path.exists() and file_path.stat().st_size > 0:
        doc = FSInputFile(file_path, filename=file_path.name)
        await call.message.bot.send_document(
            chat_id=call.message.chat.id,
            document=doc,
            caption=localize("admin.shop.logs.caption"),
        )
    else:
        await call.answer(localize("admin.shop.logs.empty"))


@router.callback_query(F.data == "statistics", HasPermissionFilter(Permission.SHOP_MANAGE))
async def statistics_callback_handler(call: CallbackQuery):
    """
    Show key shop statistics.
    """
    today_str = datetime.date.today().isoformat()

    # Use cached statistics
    if stats_cache:
        daily_stats = await stats_cache.get_daily_stats(today_str)
        global_stats = await stats_cache.get_global_stats()

        text = localize(
            "admin.shop.stats.template",
            today_users=daily_stats['users'],
            admins=global_stats['total_admins'],
            users=global_stats['total_users'],
            today_orders=daily_stats['orders'],
            all_orders=global_stats['total_revenue'],
            today_topups=daily_stats['operations'],
            system_balance=select_users_balance(),
            all_topups=select_all_operations(),
            items=global_stats['total_items'],
            goods=global_stats['total_goods'],
            categories=select_count_categories(),
            sold_count=select_count_bought_items(),
            currency=EnvKeys.PAY_CURRENCY
        )

    else:
        # Fallback on direct requests if cache is unavailable
        text = localize(
            "admin.shop.stats.template",
            today_users=select_today_users(today_str),
            admins=select_admins(),
            users=get_user_count(),
            today_orders=select_today_orders(today_str),
            all_orders=select_all_orders(),
            today_topups=select_today_operations(today_str),
            system_balance=select_users_balance(),
            all_topups=select_all_operations(),
            items=select_count_items(),
            goods=select_count_goods(),
            categories=select_count_categories(),
            sold_count=select_count_bought_items(),
            currency=EnvKeys.PAY_CURRENCY
        )

    await call.message.edit_text(text, reply_markup=back("shop_management"), parse_mode="HTML")


@router.callback_query(F.data == "admins_list", HasPermissionFilter(Permission.USERS_MANAGE))
async def admins_callback_handler(call: CallbackQuery, state: FSMContext):
    """
    Show list of admins with lazy loading pagination.
    """
    # Create paginator
    paginator = LazyPaginator(query_admins, per_page=10)

    markup = await lazy_paginated_keyboard(
        paginator=paginator,
        item_text=lambda user_id: str(user_id),
        item_callback=lambda user_id: f"show-user_admin-{user_id}",
        page=0,
        back_cb="shop_management",
        nav_cb_prefix="admins-page_",
    )

    await call.message.edit_text(localize("admin.shop.admins.title"), reply_markup=markup)

    # Save state
    await state.update_data(admins_paginator=paginator.get_state())


@router.callback_query(F.data.startswith("admins-page_"), HasPermissionFilter(Permission.USERS_MANAGE))
async def navigate_admins(call: CallbackQuery, state: FSMContext):
    """
    Pagination for admins list with lazy loading.
    """
    try:
        current_index = int(call.data.split("_")[1])
    except Exception:
        current_index = 0

    # Get saved state
    data = await state.get_data()
    paginator_state = data.get('admins_paginator')

    # Create paginator with cached state
    paginator = LazyPaginator(query_admins, per_page=10, state=paginator_state)

    markup = await lazy_paginated_keyboard(
        paginator=paginator,
        item_text=lambda user_id: str(user_id),
        item_callback=lambda user_id: f"show-user_admin-{user_id}",
        page=current_index,
        back_cb="shop_management",
        nav_cb_prefix="admins-page_",
    )

    await call.message.edit_text(localize("admin.shop.admins.title"), reply_markup=markup)

    # Update state
    await state.update_data(admins_paginator=paginator.get_state())


@router.callback_query(F.data == "users_list", HasPermissionFilter(Permission.USERS_MANAGE))
async def users_callback_handler(call: CallbackQuery, state: FSMContext):
    """
    Show list of all users with lazy loading pagination.
    """
    # Create paginator
    paginator = LazyPaginator(query_all_users, per_page=10)

    markup = await lazy_paginated_keyboard(
        paginator=paginator,
        item_text=lambda user_id: str(user_id),
        item_callback=lambda user_id: f"show-user_user-{user_id}",
        page=0,
        back_cb="shop_management",
        nav_cb_prefix="users-page_",
    )

    await call.message.edit_text(localize("admin.shop.users.title"), reply_markup=markup)

    # Save state
    await state.update_data(users_paginator=paginator.get_state())


@router.callback_query(F.data.startswith("users-page_"), HasPermissionFilter(Permission.USERS_MANAGE))
async def navigate_users(call: CallbackQuery, state: FSMContext):
    """
    Pagination for users list with lazy loading.
    """
    try:
        current_index = int(call.data.split("_")[1])
    except Exception:
        current_index = 0

    # Get saved state
    data = await state.get_data()
    paginator_state = data.get('users_paginator')

    # Create paginator with cached state
    paginator = LazyPaginator(query_all_users, per_page=10, state=paginator_state)

    markup = await lazy_paginated_keyboard(
        paginator=paginator,
        item_text=lambda user_id: str(user_id),
        item_callback=lambda user_id: f"show-user_user-{user_id}",
        page=current_index,
        back_cb="shop_management",
        nav_cb_prefix="users-page_",
    )

    await call.message.edit_text(localize("admin.shop.users.title"), reply_markup=markup)

    # Update state
    await state.update_data(users_paginator=paginator.get_state())


@router.callback_query(F.data.startswith("show-user_"), HasPermissionFilter(permission=Permission.USERS_MANAGE))
async def show_user_info(call: CallbackQuery):
    """
    Show detailed info for selected user.
    """
    query = call.data[10:]
    origin, user_id = query.split("-")  # origin: 'user' | 'admin'
    back_target = "users_list" if origin == "user" else "admins_list"

    user = check_user(user_id)
    user_info = await call.message.bot.get_chat(user_id)
    operations = select_user_operations(user_id)
    overall_balance = sum(operations) if operations else 0
    items = select_user_items(user_id)
    role = check_role_name_by_id(user.role_id)
    referrals = check_user_referrals(user.telegram_id)

    text = (
        f"{localize('profile.caption', name=user_info.first_name, id=user_id)}\n\n"
        f"{localize('profile.id', id=user_id)}\n"
        f"{localize('profile.balance', amount=user.balance, currency=EnvKeys.PAY_CURRENCY)}\n"
        f"{localize('profile.total_topup', amount=overall_balance, currency=EnvKeys.PAY_CURRENCY)}\n"
        f"{localize('profile.purchased_count', count=items)}\n\n"
        f"{localize('profile.referral_id', id=user.referral_id)}\n"
        f"{localize('admin.users.referrals', count=referrals)}\n"
        f"{localize('admin.users.role', role=role)}\n"
        f"{localize('profile.registration_date', dt=user.registration_date)}\n"
    )

    await call.message.edit_text(text, parse_mode="HTML", reply_markup=back(back_target))


@router.callback_query(F.data == "show_bought_item", HasPermissionFilter(Permission.SHOP_MANAGE))
async def show_bought_item_callback_handler(call: CallbackQuery, state: FSMContext):
    """
    Ask for purchased item's unique ID to search.
    """
    await call.message.edit_text(
        localize("admin.shop.bought.prompt_id"),
        reply_markup=back("shop_management"),
    )
    await state.set_state(GoodsFSM.waiting_bought_item_id)


@router.message(GoodsFSM.waiting_bought_item_id, F.text, HasPermissionFilter(Permission.SHOP_MANAGE))
async def process_item_show(message: Message, state: FSMContext):
    """Show purchased item details by unique ID."""
    try:
        # Validate search query
        search_query = SearchQuery(
            query=message.text.strip(),
            limit=1
        )

        # Sanitize and validate ID
        msg = search_query.sanitize_query(search_query.query)

        if not msg.isdigit():
            await message.answer(
                localize("errors.id_should_be_number"),
                reply_markup=back("show_bought_item")
            )
            return

        item = select_bought_item(int(msg))
        if item:
            # Sanitize output values
            safe_value = sanitize_html(item['value'])

            text = (
                f"{localize('purchases.item.name', name=item['item_name'])}\n"
                f"{localize('purchases.item.price', amount=item['price'], currency=EnvKeys.PAY_CURRENCY)}\n"
                f"{localize('purchases.item.datetime', dt=item['bought_datetime'])}\n"
                f"{localize('purchases.item.buyer', buyer=item['buyer_id'])}\n"
                f"{localize('purchases.item.unique_id', uid=item['unique_id'])}\n"
                f"{localize('purchases.item.value', value=safe_value)}"
            )
            await message.answer(text, parse_mode="HTML", reply_markup=back("show_bought_item"))
        else:
            await message.answer(
                localize("admin.shop.bought.not_found"),
                reply_markup=back("show_bought_item")
            )

    except Exception as e:
        await message.answer(
            localize("errors.invalid_data"),
            reply_markup=back("show_bought_item")
        )
        audit_logger.error(f"Search error: {e}")

    await state.clear()
