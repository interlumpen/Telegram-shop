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
    select_today_users, get_user_count, select_today_orders,
    select_all_orders, select_today_operations, select_users_balance, select_all_operations,
    select_count_items, select_count_goods, select_count_categories, select_count_bought_items,
    select_bought_item, check_user_referrals, check_role_name_by_id, select_user_items,
    select_user_operations, query_all_users, check_user_cached
)
from bot.database.methods.read import (
    get_roles_with_user_counts, select_unique_buyers, select_avg_order,
    select_today_orders_count, select_blocked_users_count,
)
from bot.keyboards import back, simple_buttons, lazy_paginated_keyboard
from bot.filters import HasPermissionFilter, HasAnyPermissionFilter
from bot.database.methods.audit import log_audit
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


@router.callback_query(F.data == "shop_management", HasAnyPermissionFilter(
    permissions=Permission.CATALOG_MANAGE | Permission.STATS_VIEW
))
async def shop_callback_handler(call: CallbackQuery):
    """
    Open shop-management main menu.
    Shows only items the caller has permissions for.
    """
    from bot.database.methods import check_role_cached
    role = await check_role_cached(call.from_user.id) or 0

    actions = []
    if role & Permission.STATS_VIEW:
        actions.append((localize("admin.shop.menu.statistics"), "statistics"))
        actions.append((localize("admin.shop.menu.logs"), "show_logs"))
    if role & Permission.USERS_MANAGE:
        actions.append((localize("admin.shop.menu.users"), "users_list"))
    if role & Permission.CATALOG_MANAGE:
        actions.append((localize("admin.shop.menu.search_bought"), "show_bought_item"))
    actions.append((localize("btn.back"), "console"))

    markup = simple_buttons(actions, per_row=1)
    await call.message.edit_text(localize("admin.shop.menu.title"), reply_markup=markup)


@router.callback_query(F.data == "show_logs", HasPermissionFilter(Permission.STATS_VIEW))
async def logs_callback_handler(call: CallbackQuery):
    """
    Send bot logs (audit and bot) files if they exist and are not empty.
    """
    files_to_send = []

    # Check audit log file
    audit_file_path = Path(EnvKeys.BOT_AUDITFILE)
    if audit_file_path.exists() and audit_file_path.stat().st_size > 0:
        files_to_send.append(('audit', audit_file_path))

    # Check bot log file
    bot_file_path = Path(EnvKeys.BOT_LOGFILE)
    if bot_file_path.exists() and bot_file_path.stat().st_size > 0:
        files_to_send.append(('bot', bot_file_path))

    if files_to_send:
        for log_type, file_path in files_to_send:
            doc = FSInputFile(file_path, filename=file_path.name)
            caption = localize("admin.shop.logs.caption") if log_type == 'audit' else f"{log_type.title()} log file"
            await call.message.bot.send_document(
                chat_id=call.message.chat.id,
                document=doc,
                caption=caption,
            )
    else:
        await call.answer(localize("admin.shop.logs.empty"))


@router.callback_query(F.data == "statistics", HasPermissionFilter(Permission.STATS_VIEW))
async def statistics_callback_handler(call: CallbackQuery):
    """
    Show key shop statistics.
    """
    today_str = datetime.date.today().isoformat()

    # Collect new metrics (not cached — lightweight queries)
    unique_buyers = await select_unique_buyers()
    avg_order = await select_avg_order()
    today_sold_count = await select_today_orders_count(today_str)
    blocked_count = await select_blocked_users_count()

    # Use cached statistics
    if stats_cache:
        daily_stats = await stats_cache.get_daily_stats(today_str)
        global_stats = await stats_cache.get_global_stats()

        text = localize(
            "admin.shop.stats.template",
            today_users=daily_stats['users'],
            users=global_stats['total_users'],
            buyers=unique_buyers,
            blocked=blocked_count,
            today_orders=daily_stats['orders'],
            today_sold_count=today_sold_count,
            all_orders=global_stats['total_revenue'],
            avg_order=f"{avg_order:.2f}",
            today_topups=daily_stats['operations'],
            system_balance=await select_users_balance(),
            all_topups=await select_all_operations(),
            items=global_stats['total_items'],
            goods=global_stats['total_goods'],
            categories=await select_count_categories(),
            sold_count=await select_count_bought_items(),
            currency=EnvKeys.PAY_CURRENCY
        )

    else:
        # Fallback on direct requests if cache is unavailable
        text = localize(
            "admin.shop.stats.template",
            today_users=await select_today_users(today_str),
            users=await get_user_count(),
            buyers=unique_buyers,
            blocked=blocked_count,
            today_orders=await select_today_orders(today_str),
            today_sold_count=today_sold_count,
            all_orders=await select_all_orders(),
            avg_order=f"{avg_order:.2f}",
            today_topups=await select_today_operations(today_str),
            system_balance=await select_users_balance(),
            all_topups=await select_all_operations(),
            items=await select_count_items(),
            goods=await select_count_goods(),
            categories=await select_count_categories(),
            sold_count=await select_count_bought_items(),
            currency=EnvKeys.PAY_CURRENCY
        )

    # Append role breakdown
    roles = await get_roles_with_user_counts()
    if roles:
        text += "\n" + localize("admin.shop.stats.roles_header")
        for r in roles:
            perms_list = [label for bit, label in _PERM_LABELS.items() if r['permissions'] & bit]
            perms_str = ", ".join(perms_list) if perms_list else "—"
            text += f"\n◾<b>{r['name']}</b> ({perms_str}): {r['user_count']}"

    await call.message.edit_text(text, reply_markup=back("shop_management"), parse_mode="HTML")


_PERM_LABELS = {
    Permission.USE: "USE",
    Permission.BROADCAST: "BROADCAST",
    Permission.SETTINGS_MANAGE: "SETTINGS",
    Permission.USERS_MANAGE: "USERS",
    Permission.CATALOG_MANAGE: "CATALOG",
    Permission.ADMINS_MANAGE: "ADMINS",
    Permission.OWN: "OWNER",
    Permission.STATS_VIEW: "STATS",
    Permission.BALANCE_MANAGE: "BALANCE",
    Permission.PROMO_MANAGE: "PROMOS",
}


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
    _, user_id = query.split("-")
    user_id = int(user_id)

    user = await check_user_cached(user_id)
    user_info = await call.message.bot.get_chat(user_id)
    operations = await select_user_operations(user_id)
    overall_balance = sum(operations) if operations else 0
    items = await select_user_items(user_id)
    role = await check_role_name_by_id(user.get('role_id'))
    referrals = await check_user_referrals(user.get('telegram_id'))

    text = (
        f"{localize('profile.caption', name=user_info.first_name, id=user_id)}\n\n"
        f"{localize('profile.id', id=user_id)}\n"
        f"{localize('profile.balance', amount=user.get('balance'), currency=EnvKeys.PAY_CURRENCY)}\n"
        f"{localize('profile.total_topup', amount=overall_balance, currency=EnvKeys.PAY_CURRENCY)}\n"
        f"{localize('profile.purchased_count', count=items)}\n\n"
        f"{localize('profile.referral_id', id=user.get('referral_id'))}\n"
        f"{localize('admin.users.referrals', count=referrals)}\n"
        f"{localize('admin.users.role', role=role)}\n"
        f"{localize('profile.registration_date', dt=user.get('registration_date'))}\n"
    )

    await call.message.edit_text(text, parse_mode="HTML", reply_markup=back("users_list"))


@router.callback_query(F.data == "show_bought_item", HasPermissionFilter(Permission.CATALOG_MANAGE))
async def show_bought_item_callback_handler(call: CallbackQuery, state: FSMContext):
    """
    Ask for purchased item's unique ID to search.
    """
    await call.message.edit_text(
        localize("admin.shop.bought.prompt_id"),
        reply_markup=back("shop_management"),
    )
    await state.set_state(GoodsFSM.waiting_bought_item_id)


@router.message(GoodsFSM.waiting_bought_item_id, F.text, HasPermissionFilter(Permission.CATALOG_MANAGE))
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

        item = await select_bought_item(int(msg))
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
        await log_audit("search_error", level="ERROR", details=str(e))

    await state.clear()
