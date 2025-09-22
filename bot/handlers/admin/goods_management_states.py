from functools import partial

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.handlers.other import generate_short_hash
from bot.i18n import localize
from bot.database.models import Permission
from bot.database.methods import check_item_cached, delete_item, get_item_info_cached, get_goods_info, delete_item_from_position, \
    query_items_in_position
from bot.keyboards.inline import back, simple_buttons, lazy_paginated_keyboard
from bot.logger_mesh import audit_logger
from bot.filters import HasPermissionFilter
from bot.misc import EnvKeys, LazyPaginator
from bot.states import GoodsFSM

router = Router()


@router.callback_query(F.data == 'goods_management', HasPermissionFilter(permission=Permission.SHOP_MANAGE))
async def goods_management_callback_handler(call: CallbackQuery, state):
    """
    Opens the positions (goods) management menu.
    """
    actions = [
        (localize("admin.goods.add_position"), "add_item"),
        (localize("admin.goods.add_item"), "update_item_amount"),
        (localize("admin.goods.update_position"), "update_item"),
        (localize("admin.goods.delete_position"), "delete_item"),
        (localize("admin.goods.show_items"), "show__items_in_position"),
        (localize("btn.back"), "console"),
    ]
    markup = simple_buttons(actions, per_row=1)
    await call.message.edit_text(localize('admin.goods.menu.title'), reply_markup=markup)
    await state.clear()


@router.callback_query(F.data == 'delete_item', HasPermissionFilter(permission=Permission.SHOP_MANAGE))
async def delete_item_callback_handler(call: CallbackQuery, state):
    """
    Requests a position name to delete.
    """
    await call.message.edit_text(localize('admin.goods.delete.prompt.name'), reply_markup=back("goods_management"))
    await state.set_state(GoodsFSM.waiting_item_name_delete)


@router.message(GoodsFSM.waiting_item_name_delete, F.text)
async def delete_str_item(message: Message, state):
    """
    Deletes a position by the provided name.
    """
    item_name = message.text
    item = await check_item_cached(item_name)
    if not item:
        await message.answer(
            localize('admin.goods.delete.position.not_found'),
            reply_markup=back('goods_management')
        )
    else:
        delete_item(item_name)
        await message.answer(
            localize('admin.goods.delete.position.success'),
            reply_markup=back('goods_management')
        )
        admin_info = await message.bot.get_chat(message.from_user.id)
        audit_logger.info(
            f'User {message.from_user.id} ({admin_info.first_name}) deleted the position "{item_name}"'
        )
    await state.clear()


@router.callback_query(F.data == 'show__items_in_position', HasPermissionFilter(permission=Permission.SHOP_MANAGE))
async def show_items_callback_handler(call: CallbackQuery, state):
    """
    Requests a position name to show its items.
    """
    await call.message.edit_text(localize('admin.goods.prompt.enter_item_name'), reply_markup=back("goods_management"))
    await state.set_state(GoodsFSM.waiting_item_name_show)


@router.message(GoodsFSM.waiting_item_name_show, F.text)
async def show_str_item(message: Message, state: FSMContext):
    """
    Shows all items in the selected position with lazy loading pagination.
    """
    item_name = message.text.strip()
    item = await check_item_cached(item_name)
    if not item:
        await message.answer(
            localize('admin.goods.position.not_found'),
            reply_markup=back('goods_management')
        )
        await state.clear()
        return

    # Create paginator
    query_func = partial(query_items_in_position, item_name)
    paginator = LazyPaginator(query_func, per_page=10)

    # Check if there are any items
    total = await paginator.get_total_count()
    if total == 0:
        await message.answer(
            localize('admin.goods.list_in_position.empty'),
            reply_markup=back('goods_management')
        )
        await state.clear()
        return

    # Generate a short hash for the item name to save space in callback_data
    item_hash = generate_short_hash(item_name)

    # Store mapping in state
    await state.update_data(
        item_hash_mapping={item_hash: item_name},
        current_position_name=item_name
    )

    markup = await lazy_paginated_keyboard(
        paginator=paginator,
        item_text=lambda g: str(g),
        item_callback=lambda g: f"si_{g}_{item_hash}_0",  # Shortened format
        page=0,
        back_cb="goods_management",
        nav_cb_prefix=f"gip_{item_hash}_"  # Shortened prefix
    )

    await message.answer(localize('admin.goods.list_in_position.title'), reply_markup=markup)

    # Save state
    await state.update_data(
        items_in_position_paginator=paginator.get_state()
    )


@router.callback_query(F.data.startswith('gip_'), HasPermissionFilter(permission=Permission.SHOP_MANAGE))
async def navigate_items_in_goods(call: CallbackQuery, state: FSMContext):
    """
    Paginates items inside a position with lazy loading.
    Callback data format: gip_{item_hash}_{page}
    """
    payload = call.data[4:]  # Remove 'gip_'
    try:
        item_hash, page_str = payload.rsplit('_', 1)
        current_index = int(page_str)
    except ValueError:
        item_hash, current_index = payload, 0

    # Get saved state
    data = await state.get_data()
    paginator_state = data.get('items_in_position_paginator')
    item_hash_mapping = data.get('item_hash_mapping', {})

    # Get the actual item name from hash
    item_name = item_hash_mapping.get(item_hash)
    if not item_name:
        # Try to get it from current_position_name
        item_name = data.get('current_position_name')
        if not item_name:
            await call.answer(localize('errors.invalid_data'), show_alert=True)
            return

    # Create paginator with cached state
    query_func = partial(query_items_in_position, item_name)
    paginator = LazyPaginator(query_func, per_page=10, state=paginator_state)

    # Check if there are any items
    total = await paginator.get_total_count()
    if total == 0:
        await call.message.edit_text(
            localize('admin.goods.list_in_position.empty'),
            reply_markup=back('goods_management')
        )
        return

    markup = await lazy_paginated_keyboard(
        paginator=paginator,
        item_text=lambda g: str(g),
        item_callback=lambda g: f"si_{g}_{item_hash}_{current_index}",
        page=current_index,
        back_cb="goods_management",
        nav_cb_prefix=f"gip_{item_hash}_"
    )

    await call.message.edit_text(localize('admin.goods.list_in_position.title'), reply_markup=markup)

    # Update state
    await state.update_data(
        items_in_position_paginator=paginator.get_state(),
        current_position_name=item_name,
        item_hash_mapping={item_hash: item_name}
    )


@router.callback_query(F.data.startswith('si_'), HasPermissionFilter(permission=Permission.SHOP_MANAGE))
async def item_info_callback_handler(call: CallbackQuery, state: FSMContext):
    """
    Shows details for a specific item within a position.
    Callback data format: si_{id}_{item_hash}_{page}
    """
    payload = call.data[3:]  # Remove 'si_'

    # Parse compact format
    parts = payload.split('_')
    if len(parts) < 2:
        await call.answer(localize("admin.goods.item.invalid"), show_alert=True)
        return

    item_id_str = parts[0]
    item_hash = parts[1] if len(parts) > 1 else ""
    page = parts[2] if len(parts) > 2 else "0"

    try:
        item_id = int(item_id_str)
    except ValueError:
        await call.answer(localize("admin.goods.item.invalid_id"), show_alert=True)
        return

    item_info = get_goods_info(item_id)
    if not item_info:
        await call.answer(localize("admin.goods.item.not_found"), show_alert=True)
        return

    position_info = await get_item_info_cached(item_info["item_name"])

    # Store item info in state for delete handler
    await state.update_data(
        delete_item_id=item_id,
        delete_item_hash=item_hash,
        delete_page=page,
        delete_item_name=item_info["item_name"]
    )

    actions = [
        (localize("admin.goods.item.delete.button"), f"dip_{item_id}"),  # Simplified callback
        (localize("btn.back"), f"gip_{item_hash}_{page}"),
    ]
    markup = simple_buttons(actions, per_row=1)

    text = (
        f'{localize("admin.goods.item.info.position", name=item_info["item_name"])}\n'
        f'{localize("admin.goods.item.info.price", price=position_info["price"], currency=EnvKeys.PAY_CURRENCY)}\n'
        f'{localize("admin.goods.item.info.id", id=item_info["id"])}\n'
        f'{localize("admin.goods.item.info.value", value=item_info["value"])}'
    )

    await call.message.edit_text(text, parse_mode='HTML', reply_markup=markup)


@router.callback_query(
    F.data.startswith('dip_'),  # Shortened from 'delete-item-from-position_'
    HasPermissionFilter(permission=Permission.SHOP_MANAGE)
)
async def process_delete_item_from_position(call: CallbackQuery, state: FSMContext):
    """
    Delete item from position and refresh the list with lazy loading.
    Callback data format: dip_{id}
    """
    payload = call.data[4:]  # Remove 'dip_'
    try:
        item_id = int(payload)
    except ValueError:
        await call.answer(localize("admin.goods.item.invalid"), show_alert=True)
        return

    # Get stored data from state
    data = await state.get_data()
    item_hash = data.get('delete_item_hash', '')
    page = data.get('delete_page', '0')
    item_name = data.get('delete_item_name', '')

    item_info = get_goods_info(item_id)
    if not item_info:
        await call.answer(localize("admin.goods.item.already_deleted_or_missing"), show_alert=True)
        await call.message.edit_text(
            localize("admin.goods.list_in_position.title"),
            reply_markup=back(f"gip_{item_hash}_{page}")
        )
        return

    position_name = item_info["item_name"]
    delete_item_from_position(item_id)

    # Redraw the list page if needed
    if item_hash and item_name:
        try:
            page_int = int(page)
        except Exception:
            await call.message.edit_text(
                localize('admin.goods.item.deleted'),
                reply_markup=back(f"gip_{item_hash}_{page}")
            )
            return

        # Get saved state
        paginator_state = data.get('items_in_position_paginator')

        # Create paginator with cached state (but clear cache to refresh after deletion)
        from bot.database.methods.lazy_queries import query_items_in_position
        from functools import partial
        from bot.misc.lazy_paginator import LazyPaginator

        query_func = partial(query_items_in_position, item_name)
        paginator = LazyPaginator(query_func, per_page=10, state=paginator_state)

        # Clear cache to force reload after deletion
        paginator.clear_cache()

        # Check if there are any items left
        total = await paginator.get_total_count()
        if total == 0:
            await call.message.edit_text(
                localize('admin.goods.list_in_position.empty'),
                reply_markup=back("goods_management")
            )
        else:
            # Adjust page if needed (if deleted last item on last page)
            max_page = max((total - 1) // 10, 0)
            page_int = max(0, min(page_int, max_page))

            markup = await lazy_paginated_keyboard(
                paginator=paginator,
                item_text=lambda g: str(g),
                item_callback=lambda g: f"si_{g}_{item_hash}_{page_int}",
                page=page_int,
                back_cb="goods_management",
                nav_cb_prefix=f"gip_{item_hash}_"
            )

            await call.message.edit_text(
                f'{localize("admin.goods.item.deleted")}\n\n{localize("admin.goods.list_in_position.title")}',
                reply_markup=markup
            )

            # Update state with new paginator
            await state.update_data(
                items_in_position_paginator=paginator.get_state(),
                item_hash_mapping={item_hash: item_name}
            )
    else:
        await call.message.edit_text(
            localize('admin.goods.item.deleted'),
            reply_markup=back("goods_management")
        )

    admin_info = await call.message.bot.get_chat(call.from_user.id)
    audit_logger.info(
        f"User {call.from_user.id} ({admin_info.first_name}) deleted product with id={item_id} from position {position_name or '<?>'}"
    )
