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
    select_bought_item, query_all_users, check_user_cached
)
from bot.database.methods.read import (
    get_roles_with_user_counts, select_unique_buyers, select_avg_order,
    select_today_orders_count, select_blocked_users_count, get_user_profile_aggregates,
)
from bot.keyboards import back, simple_buttons, lazy_paginated_keyboard
from bot.filters import HasPermissionFilter, HasAnyPermissionFilter
from bot.handlers.admin._common import user_profile_lines
from bot.handlers.other import display_name
from bot.database.methods.audit import log_audit
from bot.database.methods.cache_utils import safe_create_task
from bot.misc import EnvKeys, LazyPaginator, SearchQuery, StatsCache, get_cache_manager
from bot.i18n import localize, esc
from bot.states import GoodsFSM

router = Router()

# Telegram's upload ceiling for send_document.
MAX_LOG_UPLOAD_BYTES = 50 * 1024 * 1024

# Initialize StatsCache as a global variable
stats_cache: Optional[StatsCache] = None


def init_stats_cache():
    """Initializing the statistics cache"""
    global stats_cache
    cache_manager = get_cache_manager()
    if cache_manager:
        stats_cache = StatsCache(cache_manager)
        safe_create_task(stats_cache.warm_up_cache())


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
    oversized = []

    for log_type, raw_path in (('audit', EnvKeys.BOT_AUDITFILE), ('bot', EnvKeys.BOT_LOGFILE)):
        path = Path(raw_path)
        if not path.exists():
            continue
        size = path.stat().st_size
        if size == 0:
            continue
        # send_document rejects anything past Telegram's 50 MB limit; say so instead of letting the upload fail with an opaque API error.
        if size > MAX_LOG_UPLOAD_BYTES:
            oversized.append(path.name)
            continue
        files_to_send.append((log_type, path))

    if oversized:
        await call.answer(
            localize("admin.shop.logs.too_large", files=", ".join(oversized)),
            show_alert=True,
        )

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

    if stats_cache:
        roles, daily, glob, dash = await asyncio.gather(
            get_roles_with_user_counts(),
            stats_cache.get_daily_stats(today_str),
            stats_cache.get_global_stats(),
            stats_cache.get_dashboard_stats(),
        )
        today_users, today_orders = daily['users'], daily['orders']
        today_topups, today_sold_count = daily['operations'], daily['orders_count']

        users, all_orders = glob['total_users'], glob['total_revenue']
        items, goods = glob['total_items'], glob['total_goods']

        unique_buyers, avg_order = dash['unique_buyers'], dash['avg_order']
        sold_count, blocked_count = dash['sold_count'], dash['blocked_users']
        system_balance, all_topups = dash['users_balance'], dash['all_operations']
        categories = dash['categories']
    else:
        # Redis is off — no cache to populate, so fall back to individual reads.
        (
            roles,
            today_users, today_orders, today_topups, today_sold_count,
            users, all_orders, items, goods,
            unique_buyers, avg_order, sold_count, blocked_count,
            system_balance, all_topups, categories,
        ) = await asyncio.gather(
            get_roles_with_user_counts(),
            select_today_users(today_str),
            select_today_orders(today_str),
            select_today_operations(today_str),
            select_today_orders_count(today_str),
            get_user_count(),
            select_all_orders(),
            select_count_items(),
            select_count_goods(),
            select_unique_buyers(),
            select_avg_order(),
            select_count_bought_items(),
            select_blocked_users_count(),
            select_users_balance(),
            select_all_operations(),
            select_count_categories(),
        )

    text = localize(
        "admin.shop.stats.template",
        today_users=today_users,
        users=users,
        buyers=unique_buyers,
        blocked=blocked_count,
        today_orders=today_orders,
        today_sold_count=today_sold_count,
        all_orders=all_orders,
        avg_order=f"{avg_order:.2f}",
        today_topups=today_topups,
        system_balance=system_balance,
        all_topups=all_topups,
        items=items,
        goods=goods,
        categories=categories,
        sold_count=sold_count,
        currency=EnvKeys.PAY_CURRENCY
    )

    # Append role breakdown
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


async def _show_users_page(call: CallbackQuery, state: FSMContext, page: int):
    """Render one page of the all-users list (shared by the view and paginate handlers)."""
    paginator = LazyPaginator(query_all_users, per_page=10)

    markup = await lazy_paginated_keyboard(
        paginator=paginator,
        item_text=lambda user_id: str(user_id),
        item_callback=lambda user_id: f"show-user_user-{user_id}",
        page=page,
        back_cb="shop_management",
        nav_cb_prefix="users-page_",
    )

    await call.message.edit_text(localize("admin.shop.users.title"), reply_markup=markup)


@router.callback_query(F.data == "users_list", HasPermissionFilter(Permission.USERS_MANAGE))
async def users_callback_handler(call: CallbackQuery, state: FSMContext):
    """Show list of all users with lazy loading pagination."""
    await _show_users_page(call, state, 0)


@router.callback_query(F.data.startswith("users-page_"), HasPermissionFilter(Permission.USERS_MANAGE))
async def navigate_users(call: CallbackQuery, state: FSMContext):
    """Pagination for users list with lazy loading."""
    try:
        page = int(call.data.split("_")[1])
    except Exception:
        page = 0
    await _show_users_page(call, state, page)


@router.callback_query(F.data.startswith("show-user_"), HasPermissionFilter(permission=Permission.USERS_MANAGE))
async def show_user_info(call: CallbackQuery):
    """
    Show detailed info for selected user.
    Callback data format: show-user_user-{user_id}
    """
    try:
        user_id = int(call.data[len("show-user_"):].split("-", 1)[1])
    except (ValueError, IndexError):
        await call.answer(localize("errors.invalid_data"), show_alert=True)
        return

    user = await check_user_cached(user_id)
    if not user:
        await call.answer(localize("admin.users.not_found"), show_alert=True)
        return

    first_name, agg = await asyncio.gather(
        display_name(call.message.bot, user_id),
        get_user_profile_aggregates(user_id, user.get('role_id')),
    )

    text = '\n'.join(user_profile_lines(
        user, first_name, user_id,
        overall_balance=agg['operations_total'], items_count=agg['items_count'],
        role=agg['role_name'], referrals=agg['referrals'], include_referral_id=True,
    )) + '\n'

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
            # Escaped: this must render exactly what was delivered to the buyer, tags and all.
            safe_value = esc(item['value'])

            text = (
                f"{localize('purchases.item.name', name=esc(item['item_name']))}\n"
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
