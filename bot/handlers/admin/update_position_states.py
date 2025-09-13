from urllib.parse import urlparse

from aiogram import Router, F
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest, TelegramNotFound
from aiogram.types import CallbackQuery, Message

from bot.database.models import Permission
from bot.database.methods import check_item_cached, add_values_to_item, update_item, check_value, delete_only_items

from bot.keyboards.inline import back, question_buttons, simple_buttons
from bot.logger_mesh import audit_logger
from bot.filters import HasPermissionFilter
from bot.misc import EnvKeys
from bot.i18n import localize
from bot.states import UpdateItemFSM

router = Router()


@router.callback_query(F.data == 'update_item_amount', HasPermissionFilter(permission=Permission.SHOP_MANAGE))
async def update_item_amount_callback_handler(call: CallbackQuery, state):
    """Starts the flow for adding values (stock) to an existing item."""
    await call.message.edit_text(
        localize('admin.goods.update.amount.prompt.name'),
        reply_markup=back("goods_management")
    )
    await state.set_state(UpdateItemFSM.waiting_item_name_for_amount_upd)


@router.message(UpdateItemFSM.waiting_item_name_for_amount_upd, F.text)
async def check_item_name_for_amount_upd(message: Message, state):
    """
    Validate that item exists and is NOT infinite.
    If item is infinite — values cannot be added.
    """
    item_name = message.text.strip()
    item = await check_item_cached(item_name)
    if not item:
        await message.answer(
            localize('admin.goods.update.amount.not_exists'),
            reply_markup=back('goods_management')
        )
        return

    # If item is infinite, we logically can't add individual values
    if check_value(item_name):
        await message.answer(
            localize('admin.goods.update.amount.infinity_forbidden'),
            reply_markup=back('goods_management')
        )
        return

    # Otherwise start collecting values
    await state.update_data(item_name=item_name)
    await message.answer(
        localize('admin.goods.add.values.prompt_multi'),
        reply_markup=back("goods_management")
    )
    await state.set_state(UpdateItemFSM.waiting_item_values_upd)


@router.message(UpdateItemFSM.waiting_item_values_upd, F.text)
async def updating_item_values(message: Message, state):
    """
    Accumulate values for the item (regular mode).
    Show "Finish" button after first value.
    """
    data = await state.get_data()
    values = data.get('item_values', [])
    values.append(message.text)
    await state.update_data(item_values=values)

    await message.answer(
        localize('admin.goods.add.values.added', value=message.text, count=len(values)),
        reply_markup=simple_buttons([
            (localize('btn.add_values_finish'), "finish_updating_items"),
            (localize('btn.back'), "goods_management")
        ], per_row=1)
    )


@router.callback_query(F.data == 'finish_updating_items', UpdateItemFSM.waiting_item_values_upd)
async def updating_item_amount(call: CallbackQuery, state):
    """Finish adding new item values."""
    data = await state.get_data()
    item_name = data.get('item_name')
    raw_values: list[str] = data.get("item_values", []) or []

    added = 0
    skipped_db_dup = 0
    skipped_batch_dup = 0
    skipped_invalid = 0
    seen_in_batch: set[str] = set()

    for v in raw_values:
        v_norm = (v or "").strip()
        if not v_norm:
            skipped_invalid += 1
            continue

        # Duplicate inside current batch
        if v_norm in seen_in_batch:
            skipped_batch_dup += 1
            continue
        seen_in_batch.add(v_norm)

        # Try insert — False means it already exists in DB
        if add_values_to_item(item_name, v_norm, False):
            added += 1
        else:
            skipped_db_dup += 1

    text_lines = [
        localize('admin.goods.update.values.result.title'),
        localize('admin.goods.add.result.added', n=added),
    ]
    if skipped_db_dup:
        text_lines.append(localize('admin.goods.add.result.skipped_db_dup', n=skipped_db_dup))
    if skipped_batch_dup:
        text_lines.append(localize('admin.goods.add.result.skipped_batch_dup', n=skipped_batch_dup))
    if skipped_invalid:
        text_lines.append(localize('admin.goods.add.result.skipped_invalid', n=skipped_invalid))

    await call.message.edit_text("\n".join(text_lines), parse_mode="HTML", reply_markup=back('goods_management'))

    # Optional: channel notification (if configured)
    channel_url = EnvKeys.CHANNEL_URL or ""
    parsed = urlparse(channel_url)
    channel_username = (
                           parsed.path.lstrip('/')
                           if parsed.path else channel_url.replace("https://t.me/", "").replace("t.me/", "").lstrip('@')
                       ) or None
    if channel_username:
        try:
            await call.bot.send_message(
                chat_id=f"@{channel_username}",
                text=(
                    f'🎁 {localize("shop.group.new_upload")}\n'
                    f'🏷️ {localize("shop.group.item")}: <b>{item_name}</b>\n'
                    f'📦 {localize("shop.group.count")}: <b>{added}</b>'
                ),
                parse_mode='HTML'
            )
        except TelegramForbiddenError:
            await call.answer(localize("errors.channel.telegram_forbidden_error", channel=channel_username))
        except TelegramNotFound:
            await call.answer(localize("errors.channel.telegram_not_found", channel=channel_username))
        except TelegramBadRequest as e:
            await call.answer(localize("errors.channel.telegram_bad_request", e=e))

    admin_info = await call.message.bot.get_chat(call.from_user.id)
    audit_logger.info(
        f'Admin {call.from_user.id} ({admin_info.first_name}) added {added} value(s) to item "{item_name}".'
    )
    await state.clear()


@router.callback_query(F.data == 'update_item', HasPermissionFilter(permission=Permission.SHOP_MANAGE))
async def update_item_callback_handler(call: CallbackQuery, state):
    """Starts the full update flow."""
    await call.message.edit_text(localize('admin.goods.update.prompt.name'), reply_markup=back("goods_management"))
    await state.set_state(UpdateItemFSM.waiting_item_name_for_update)


@router.message(UpdateItemFSM.waiting_item_name_for_update, F.text)
async def check_item_name_for_update(message: Message, state):
    """Validate item and ask for a new name."""
    item_name = message.text.strip()
    item = await check_item_cached(item_name)
    if not item:
        await message.answer(
            localize('admin.goods.update.not_exists'),
            reply_markup=back('goods_management')
        )
        return

    await state.update_data(item_old_name=item_name, item_category=item['category_name'])
    await message.answer(localize('admin.goods.update.prompt.new_name'), reply_markup=back('goods_management'))
    await state.set_state(UpdateItemFSM.waiting_item_new_name)


@router.message(UpdateItemFSM.waiting_item_new_name, F.text)
async def update_item_name(message: Message, state):
    """Ask for item description."""
    await state.update_data(item_new_name=message.text.strip())
    await message.answer(localize('admin.goods.update.prompt.description'), reply_markup=back('goods_management'))
    await state.set_state(UpdateItemFSM.waiting_item_description)


@router.message(UpdateItemFSM.waiting_item_description, F.text)
async def update_item_description(message: Message, state):
    """Ask for new price."""
    await state.update_data(item_description=message.text.strip())
    await message.answer(localize('admin.goods.add.prompt.price', currency=EnvKeys.PAY_CURRENCY),
                         reply_markup=back('goods_management'))
    await state.set_state(UpdateItemFSM.waiting_item_price)


@router.message(UpdateItemFSM.waiting_item_price, F.text)
async def update_item_price(message: Message, state):
    """Validate price and ask about infinity mode."""
    price_text = message.text.strip()
    if not price_text.isdigit():
        await message.answer(localize('admin.goods.add.price.invalid'), reply_markup=back('goods_management'))
        return

    await state.update_data(item_price=int(price_text))
    data = await state.get_data()
    item_old_name = data.get('item_old_name')

    # If the item is NOT infinite now — ask to make it infinite
    if not check_value(item_old_name):
        await message.answer(
            localize('admin.goods.update.infinity.make.question'),
            reply_markup=question_buttons('change_make_infinity', 'goods_management')
        )
    else:
        # Otherwise ask to disable infinity
        await message.answer(
            localize('admin.goods.update.infinity.deny.question'),
            reply_markup=question_buttons('change_deny_infinity', 'goods_management')
        )
    await state.set_state(UpdateItemFSM.waiting_make_infinity)


@router.callback_query(F.data.startswith('change_'), UpdateItemFSM.waiting_make_infinity)
async def update_item_process(call: CallbackQuery, state):
    """
    Handle infinity decision:
    - change_*_no   -> just update meta without changing values,
    - change_make_* -> expect ONE value and switch to infinite,
    - change_deny_* -> expect MANY values and switch to regular.
    """
    parts = call.data.split('_')
    # Expected: change_make_infinity_yes/no, change_deny_infinity_yes/no
    decision_scope = parts[1]  # make / deny
    decision_yesno = parts[3]  # yes / no

    data = await state.get_data()
    item_old_name = data.get('item_old_name')
    item_new_name = data.get('item_new_name')
    item_description = data.get('item_description')
    category = data.get('item_category')
    price = data.get('item_price')

    if decision_yesno == 'no':
        # No type change (keep infinity/regular), update meta only
        update_item(item_old_name, item_new_name, item_description, price, category)
        await call.message.edit_text(localize('admin.goods.update.success'), reply_markup=back('goods_management'))
        admin_info = await call.message.bot.get_chat(call.from_user.id)
        audit_logger.info(
            f'Admin {call.from_user.id} ({admin_info.first_name}) updated item "{item_old_name}" → "{item_new_name}".'
        )
        await state.clear()
        return

    # decision_yesno == 'yes'
    if decision_scope == 'make':
        # Switch to infinite mode: expect a single value
        await call.message.edit_text(
            localize('admin.goods.add.single.prompt_value'),
            reply_markup=back('goods_management')
        )
        await state.set_state(UpdateItemFSM.waiting_single_value)
    else:
        # Switch to regular mode: collect many values
        await call.message.edit_text(
            localize('admin.goods.add.values.prompt_multi'),
            reply_markup=back("goods_management")
        )
        await state.set_state(UpdateItemFSM.waiting_multiple_values)


@router.message(UpdateItemFSM.waiting_single_value, F.text)
async def update_item_infinity(message: Message, state):
    """
    Switch to infinite mode:
    - purge current values,
    - add a single value with is_infinity=True,
    - update item meta.
    """
    data = await state.get_data()
    item_old_name = data.get('item_old_name')
    item_new_name = data.get('item_new_name')
    item_description = data.get('item_description')
    category = data.get('item_category')
    price = data.get('item_price')
    value = message.text

    delete_only_items(item_old_name)
    add_values_to_item(item_old_name, value, True)
    update_item(item_old_name, item_new_name, item_description, price, category)

    await message.answer(localize('admin.goods.update.success'), reply_markup=back('goods_management'))
    admin_info = await message.bot.get_chat(message.from_user.id)
    audit_logger.info(
        f'Admin {message.from_user.id} ({admin_info.first_name}) updated item "{item_old_name}" → "{item_new_name}".'
    )
    await state.clear()


@router.message(UpdateItemFSM.waiting_multiple_values, F.text)
async def updating_item(message: Message, state):
    """
    Switch to regular (non-infinite) mode:
    - accumulate values,
    - then apply changes with the “Finish” button.
    """
    data = await state.get_data()
    values = data.get('item_values', [])
    values.append(message.text)
    await state.update_data(item_values=values)

    await message.answer(
        localize('admin.goods.add.values.added', value=message.text, count=len(values)),
        reply_markup=simple_buttons([
            (localize('btn.add_values_finish'), "finish_update_item"),
            (localize('btn.back'), "goods_management")
        ], per_row=1)
    )


@router.callback_query(F.data == 'finish_update_item', UpdateItemFSM.waiting_multiple_values)
async def update_item_no_infinity(call: CallbackQuery, state):
    """
    Finalize switch to regular mode:
    - purge current values,
    - add all collected values with is_infinity=False,
    - update item meta.
    """
    data = await state.get_data()
    item_old_name = data.get('item_old_name')
    item_new_name = data.get('item_new_name')
    item_description = data.get('item_description')
    category = data.get('item_category')
    price = data.get('item_price')
    raw_values: list[str] = data.get("item_values", []) or []

    added = 0
    skipped_db_dup = 0
    skipped_batch_dup = 0
    skipped_invalid = 0
    seen_in_batch: set[str] = set()

    delete_only_items(item_old_name)

    for v in raw_values:
        v_norm = (v or "").strip()
        if not v_norm:
            skipped_invalid += 1
            continue

        if v_norm in seen_in_batch:
            skipped_batch_dup += 1
            continue
        seen_in_batch.add(v_norm)

        if add_values_to_item(item_old_name, v_norm, False):
            added += 1
        else:
            skipped_db_dup += 1

    # Update meta after values are in place
    update_item(item_old_name, item_new_name, item_description, price, category)

    text_lines = [
        localize('admin.goods.update.success'),
        localize('admin.goods.add.result.added', n=added),
    ]
    if skipped_db_dup:
        text_lines.append(localize('admin.goods.add.result.skipped_db_dup', n=skipped_db_dup))
    if skipped_batch_dup:
        text_lines.append(localize('admin.goods.add.result.skipped_batch_dup', n=skipped_batch_dup))
    if skipped_invalid:
        text_lines.append(localize('admin.goods.add.result.skipped_invalid', n=skipped_invalid))

    # Optional: channel notification (if configured)
    channel_url = EnvKeys.CHANNEL_URL or ""
    parsed = urlparse(channel_url)
    channel_username = (
                           parsed.path.lstrip('/')
                           if parsed.path else channel_url.replace("https://t.me/", "").replace("t.me/", "").lstrip('@')
                       ) or None
    if channel_username:
        try:
            await call.bot.send_message(
                chat_id=f"@{channel_username}",
                text=(
                    f'🎁 {localize("shop.group.new_upload")}\n'
                    f'🏷️ {localize("shop.group.item")}: <b>{item_new_name}</b>\n'
                    f'📦 {localize("shop.group.count")}: <b>{added}</b>'
                ),
                parse_mode='HTML'
            )
        except TelegramForbiddenError:
            await call.answer(localize("errors.channel.telegram_forbidden_error", channel=channel_username))
        except TelegramNotFound:
            await call.answer(localize("errors.channel.telegram_not_found", channel=channel_username))
        except TelegramBadRequest as e:
            await call.answer(localize("errors.channel.telegram_bad_request", e=e))

    await call.message.edit_text("\n".join(text_lines), parse_mode="HTML", reply_markup=back('goods_management'))
    admin_info = await call.message.bot.get_chat(call.from_user.id)
    audit_logger.info(
        f'Admin {call.from_user.id} ({admin_info.first_name}) updated item "{item_old_name}" → "{item_new_name}".'
    )
    await state.clear()
