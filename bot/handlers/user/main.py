from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.enums.chat_type import ChatType
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

import asyncio
import datetime
from html import escape as _esc

from bot.database.methods import (
    select_max_role_id, create_user, check_role_cached, check_user,
    select_user_operations_total, select_user_items, check_user_cached
)
from bot.database.methods.read import get_cart_count, invalidate_user_cache
from bot.database.methods.lazy_queries import query_user_operations_history
from bot.handlers.other import check_sub_channel, _parse_channel_username
from bot.keyboards import main_menu, back, profile_keyboard, check_sub
from bot.misc import EnvKeys
from bot.misc.metrics import get_metrics
from bot.i18n import localize
from bot.logger_mesh import logger

router = Router()


async def _ensure_user(user_id: int) -> dict | None:
    """Return the user's row, registering them first if it is missing.

    A stale keyboard (or a wiped database) can hand a callback from someone
    with no row at all; every screen that reads user fields needs the row to
    exist rather than blowing up on None.
    """
    user = await check_user_cached(user_id)
    if user:
        return user

    await create_user(
        telegram_id=user_id,
        registration_date=datetime.datetime.now(datetime.timezone.utc),
        referral_id=None,
        role=1,
    )
    await invalidate_user_cache(user_id)
    return await check_user_cached(user_id)


def _channel_chat_id(channel_username: str) -> int | str:
    """Resolve the chat id to query for the subscription check.

    CHANNEL_ID wins when set (private channels have no username to address), but
    a non-numeric value in the env must not take the handler down with it.
    """
    raw = EnvKeys.CHANNEL_ID
    if raw:
        try:
            return int(raw)
        except (TypeError, ValueError):
            logger.warning("CHANNEL_ID=%r is not a valid chat id; falling back to @%s", raw, channel_username)
    return f"@{channel_username}"


async def _delete_quietly(message: Message) -> None:
    """Delete a message, tolerating the cases Telegram refuses.

    A message older than 48h, or one in a chat where the bot lost delete rights,
    raises — and that must not abort a handler that already did its real work.
    """
    try:
        await message.delete()
    except (TelegramBadRequest, TelegramForbiddenError) as e:
        logger.debug(f"Failed to delete message: {e}")


async def _is_subscribed(bot, channel_username: str, user_id: int) -> bool | None:
    """Whether the user is in the required channel.

    Returns None when the check could not be performed (private channel, bad
    link, bot not an admin) so callers can treat it as "don't block".
    """
    try:
        chat_member = await bot.get_chat_member(
            chat_id=_channel_chat_id(channel_username), user_id=user_id
        )
    except (TelegramBadRequest, TelegramForbiddenError) as e:
        logger.warning(f"Channel subscription check failed for user {user_id}: {e}")
        return None
    return await check_sub_channel(chat_member)


@router.message(F.text.startswith('/start'))
async def start(message: Message, state: FSMContext):
    """
    Handle /start:
    - Ensure user exists (register if new)
    - (Optional) Check channel subscription
    - Show the main menu
    """
    if message.chat.type != ChatType.PRIVATE:
        return

    user_id = message.from_user.id
    await state.clear()

    role_data = await check_role_cached(user_id)

    if role_data == 0:
        owner_max_role = await select_max_role_id()
        user_role = owner_max_role if user_id == EnvKeys.OWNER_ID else 1

        referral_id = None
        parts = message.text.split(maxsplit=1)
        if len(parts) > 1:
            payload = parts[1].strip()
            if payload.isdigit() and payload != str(user_id):
                candidate = int(payload)
                if await check_user(candidate) is not None:
                    referral_id = candidate

        # registration_date is DateTime
        await create_user(
            telegram_id=int(user_id),
            registration_date=datetime.datetime.now(datetime.timezone.utc),
            referral_id=referral_id,
            role=user_role
        )

        await invalidate_user_cache(user_id)
        from bot.middleware.security import invalidate_auth_caches
        invalidate_auth_caches(user_id)

        metrics = get_metrics()
        if metrics:
            metrics.track_event("registration", user_id)

        # Re-read (now cached) so the menu reflects the freshly assigned role.
        role_data = await check_role_cached(user_id)

    channel_username = _parse_channel_username()

    # Optional subscription check. A failed check (None) does not block entry.
    if channel_username:
        subscribed = await _is_subscribed(message.bot, channel_username, user_id)
        if subscribed is False:
            await message.answer(localize("subscribe.prompt"), reply_markup=check_sub(channel_username))
            await _delete_quietly(message)
            return

    markup = main_menu(role=role_data, channel=channel_username, helper=EnvKeys.HELPER_ID)
    await message.answer(localize("menu.title"), reply_markup=markup)
    await _delete_quietly(message)
    await state.clear()


@router.callback_query(F.data == "back_to_menu")
async def back_to_menu_callback_handler(call: CallbackQuery, state: FSMContext):
    """
    Return user to the main menu.
    """
    user_id = call.from_user.id
    await _ensure_user(user_id)

    role = await check_role_cached(user_id) or 0

    channel_username = _parse_channel_username()

    markup = main_menu(role=role, channel=channel_username, helper=EnvKeys.HELPER_ID)
    await call.message.edit_text(localize("menu.title"), reply_markup=markup)
    await state.clear()


@router.callback_query(F.data == "rules")
async def rules_callback_handler(call: CallbackQuery, state: FSMContext):
    """
    Show rules text if provided in ENV.
    """
    rules_data = EnvKeys.RULES
    if rules_data:
        await call.message.edit_text(rules_data, reply_markup=back("back_to_menu"))
    else:
        await call.answer(localize("rules.not_set"))
    await state.clear()


@router.callback_query(F.data == "profile")
async def profile_callback_handler(call: CallbackQuery, state: FSMContext):
    """
    Send profile info (balance, purchases count, id, etc.).
    """
    user_id = call.from_user.id
    tg_user = call.from_user
    user_info = await _ensure_user(user_id)
    if not user_info:
        await call.answer(localize("errors.something_wrong"), show_alert=True)
        return

    balance = user_info.get('balance')
    overall_balance, items, cart_count = await asyncio.gather(
        select_user_operations_total(user_id),
        select_user_items(user_id),
        get_cart_count(user_id),
    )
    referral = EnvKeys.REFERRAL_PERCENT

    markup = profile_keyboard(referral, items, cart_count=cart_count)
    text = (
        f"{localize('profile.caption', name=_esc(tg_user.first_name or ''), id=user_id)}\n"
        f"{localize('profile.id', id=user_id)}\n"
        f"{localize('profile.balance', amount=balance, currency=EnvKeys.PAY_CURRENCY)}\n"
        f"{localize('profile.total_topup', amount=overall_balance, currency=EnvKeys.PAY_CURRENCY)}\n"
        f"{localize('profile.purchased_count', count=items)}"
    )
    try:
        await call.message.edit_text(text, reply_markup=markup, parse_mode='HTML')
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise
    await state.clear()


@router.callback_query(F.data == "sub_channel_done")
async def check_sub_to_channel(call: CallbackQuery, state: FSMContext):
    """
    Re-check channel subscription after user clicks "Check".
    """
    user_id = call.from_user.id
    channel_username = _parse_channel_username()
    helper = EnvKeys.HELPER_ID

    if channel_username:
        # None (check unavailable) is treated as subscribed, matching /start: a misconfigured channel must not lock everyone out of the bot.
        if await _is_subscribed(call.bot, channel_username, user_id) is not False:
            await _ensure_user(user_id)
            role = await check_role_cached(user_id) or 0
            markup = main_menu(role, channel_username, helper)
            await call.message.edit_text(localize("menu.title"), reply_markup=markup)
            await state.clear()
            return

    await call.answer(localize("errors.not_subscribed"))


# --- Operation History ---

@router.callback_query(F.data == "operation_history")
async def operation_history_handler(call: CallbackQuery, state: FSMContext):
    user_id = call.from_user.id
    await _show_operations_page(call, state, user_id, 0)


@router.callback_query(F.data.startswith("ops-page_"))
async def navigate_operations(call: CallbackQuery, state: FSMContext):
    try:
        page = int(call.data.split("_")[1])
    except (ValueError, IndexError):
        await call.answer(localize("errors.pagination_invalid"))
        return
    await _show_operations_page(call, state, call.from_user.id, page)


async def _show_operations_page(call: CallbackQuery, state: FSMContext, user_id: int, page: int):
    from functools import partial
    from bot.misc import LazyPaginator

    paginator = LazyPaginator(partial(query_user_operations_history, user_id), per_page=10)
    items = await paginator.get_page(page)
    total_pages = await paginator.get_total_pages()

    if not items:
        await call.message.edit_text(
            localize("history.title") + "\n\n" + localize("history.empty"),
            reply_markup=back("profile"),
        )
        return

    lines = [localize("history.title"), ""]
    for op in items:
        op_type = op['type']
        amount = op['amount']
        date = op['date']
        date_str = str(date)[:19] if date else ""

        if op_type == 'topup':
            lines.append(localize("history.topup", amount=amount, currency=EnvKeys.PAY_CURRENCY))
        elif op_type == 'purchase':
            lines.append(localize("history.purchase", amount=amount, currency=EnvKeys.PAY_CURRENCY))
        elif op_type == 'referral':
            lines.append(localize("history.referral", amount=amount, currency=EnvKeys.PAY_CURRENCY))
        lines.append(localize("history.date", date=date_str))
        lines.append("")

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    kb = InlineKeyboardBuilder()
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="◀️", callback_data=f"ops-page_{page - 1}"))
    if total_pages > 1:
        nav_buttons.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="dummy_button"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(text="▶️", callback_data=f"ops-page_{page + 1}"))
    if nav_buttons:
        kb.row(*nav_buttons)
    kb.row(InlineKeyboardButton(text=localize("btn.back"), callback_data="profile"))

    await call.message.edit_text("\n".join(lines), reply_markup=kb.as_markup())


