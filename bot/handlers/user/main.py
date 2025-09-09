from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.enums.chat_type import ChatType
from aiogram.fsm.context import FSMContext

from urllib.parse import urlparse
import datetime

from bot.database.methods import (
    select_max_role_id, create_user, check_role, check_user,
    select_user_operations, select_user_items
)
from bot.handlers.other import check_sub_channel
from bot.keyboards import main_menu, back, profile_keyboard, check_sub
from bot.misc import EnvKeys
from bot.i18n import localize

router = Router()


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

    owner_max_role = select_max_role_id()
    referral_id = message.text[7:] if message.text[7:] != str(user_id) else None
    user_role = owner_max_role if str(user_id) == EnvKeys.OWNER_ID else 1

    # registration_date is DateTime
    create_user(
        telegram_id=int(user_id),
        registration_date=datetime.datetime.now(),
        referral_id=int(referral_id) if referral_id else None,
        role=user_role
    )

    # Parse channel username safely from ENV
    channel_url = EnvKeys.CHANNEL_URL or ""
    parsed = urlparse(channel_url)
    channel_username = (
                           parsed.path.lstrip('/')
                           if parsed.path else channel_url.replace("https://t.me/", "").replace("t.me/", "").lstrip('@')
                       ) or None

    role_data = check_role(user_id)

    # Optional subscription check
    try:
        if channel_username:
            chat_member = await message.bot.get_chat_member(chat_id=f'@{channel_username}', user_id=user_id)
            if not await check_sub_channel(chat_member):
                markup = check_sub(channel_username)
                await message.answer(localize("subscribe.prompt"), reply_markup=markup)
                await message.delete()
                return
    except Exception:
        # Ignore channel errors (private channel, wrong link, etc.)
        pass

    markup = main_menu(role=role_data, channel=channel_username, helper=EnvKeys.HELPER_ID)
    await message.answer(localize("menu.title"), reply_markup=markup)
    await message.delete()
    await state.clear()


@router.callback_query(F.data == "back_to_menu")
async def back_to_menu_callback_handler(call: CallbackQuery, state: FSMContext):
    """
    Return user to the main menu.
    """
    user_id = call.from_user.id
    user = check_user(user_id)

    channel_url = EnvKeys.CHANNEL_URL or ""
    parsed = urlparse(channel_url)
    channel_username = (
                           parsed.path.lstrip('/')
                           if parsed.path else channel_url.replace("https://t.me/", "").replace("t.me/", "").lstrip('@')
                       ) or None

    markup = main_menu(role=user.role_id, channel=channel_username, helper=EnvKeys.HELPER_ID)
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
    user_info = check_user(user_id)
    balance = user_info.balance
    operations = select_user_operations(user_id)
    overall_balance = sum(operations) if operations else 0
    items = select_user_items(user_id)
    referral = EnvKeys.REFERRAL_PERCENT

    markup = profile_keyboard(referral, items)
    text = (
        f"{localize('profile.caption', name=tg_user.first_name, id=user_id)}\n"
        f"{localize('profile.id', id=user_id)}\n"
        f"{localize('profile.balance', amount=balance, currency=EnvKeys.PAY_CURRENCY)}\n"
        f"{localize('profile.total_topup', amount=overall_balance, currency=EnvKeys.PAY_CURRENCY)}\n"
        f"{localize('profile.purchased_count', count=items)}"
    )
    await call.message.edit_text(text, reply_markup=markup, parse_mode='HTML')
    await state.clear()


@router.callback_query(F.data == "sub_channel_done")
async def check_sub_to_channel(call: CallbackQuery, state: FSMContext):
    """
    Re-check channel subscription after user clicks "Check".
    """
    user_id = call.from_user.id
    chat = EnvKeys.CHANNEL_URL or ""
    parsed_url = urlparse(chat)
    channel_username = (
                           parsed_url.path.lstrip('/')
                           if parsed_url.path else chat.replace("https://t.me/", "").replace("t.me/", "").lstrip('@')
                       ) or None
    helper = EnvKeys.HELPER_ID

    if channel_username:
        chat_member = await call.bot.get_chat_member(chat_id='@' + channel_username, user_id=user_id)
        if await check_sub_channel(chat_member):
            user = check_user(user_id)
            markup = main_menu(user.role_id, channel_username, helper)
            await call.message.edit_text(localize("menu.title"), reply_markup=markup)
            await state.clear()
            return

    await call.answer(localize("errors.not_subscribed"))
