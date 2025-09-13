from functools import partial

from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext

from bot.database.methods import (
    get_bought_item_info, check_value, query_categories, query_user_bought_items, get_item_info_cached,
    select_item_values_amount_cached
)
from bot.keyboards import item_info, back, lazy_paginated_keyboard
from bot.i18n import localize
from bot.misc import EnvKeys, LazyPaginator
from bot.states import ShopStates

router = Router()


@router.callback_query(F.data == "shop")
async def shop_callback_handler(call: CallbackQuery, state: FSMContext):
    """
    Show list of shop categories with lazy loading.
    """
    # Create paginator
    paginator = LazyPaginator(query_categories, per_page=10)

    # Create keyboard
    markup = await lazy_paginated_keyboard(
        paginator=paginator,
        item_text=lambda cat: cat,
        item_callback=lambda cat: f"category_{cat}_categories-page_0",  # Include page info
        page=0,
        back_cb="back_to_menu",
        nav_cb_prefix="categories-page_",
    )

    await call.message.edit_text(localize("shop.categories.title"), reply_markup=markup)

    # Save paginator state
    await state.update_data(categories_paginator=paginator.get_state())
    await state.set_state(ShopStates.viewing_categories)


@router.callback_query(F.data.startswith('categories-page_'))
async def navigate_categories(call: CallbackQuery, state: FSMContext):
    """
    Pagination across shop categories with cache.
    """
    parts = call.data.split('_', 1)
    page = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0

    # Get saved state
    data = await state.get_data()
    paginator_state = data.get('categories_paginator')

    # Create paginator with cached state
    paginator = LazyPaginator(
        query_categories,
        per_page=10,
        state=paginator_state
    )

    markup = await lazy_paginated_keyboard(
        paginator=paginator,
        item_text=lambda cat: cat,
        item_callback=lambda cat: f"category_{cat}_categories-page_{page}",  # Pass current page
        page=page,
        back_cb="back_to_menu",
        nav_cb_prefix="categories-page_"
    )

    await call.message.edit_text(localize('shop.categories.title'), reply_markup=markup)

    # Update state
    await state.update_data(categories_paginator=paginator.get_state())


@router.callback_query(F.data.startswith('category_'))
async def items_list_callback_handler(call: CallbackQuery, state: FSMContext):
    """
    Show items of selected category.
    Extract category name and return page from callback_data.
    """
    # Parse callback data: category_{name}_categories-page_{page}
    callback_data = call.data[9:]  # Remove 'category_'

    if '_categories-page_' in callback_data:
        category_name, back_data = callback_data.rsplit('_categories-page_', 1)
        back_data = f"categories-page_{back_data}"
    else:
        category_name = callback_data
        back_data = "shop"

    # Create paginator for items in category
    from bot.database.methods.lazy_queries import query_items_in_category
    from functools import partial

    query_func = partial(query_items_in_category, category_name)
    paginator = LazyPaginator(query_func, per_page=10)

    markup = await lazy_paginated_keyboard(
        paginator=paginator,
        item_text=lambda item: item,
        item_callback=lambda item: f"item_{item}_{category_name}_goods-page_{category_name}_0",
        page=0,
        back_cb=back_data,  # Use the saved page
        nav_cb_prefix=f"goods-page_{category_name}_",
    )

    await call.message.edit_text(localize("shop.goods.choose"), reply_markup=markup)

    # Save state
    await state.update_data(
        goods_paginator=paginator.get_state(),
        current_category=category_name
    )
    await state.set_state(ShopStates.viewing_goods)


@router.callback_query(F.data.startswith('goods-page_'), ShopStates.viewing_goods)
async def navigate_goods(call: CallbackQuery, state: FSMContext):
    """
    Pagination for items inside selected category.
    Format: goods-page_{category}_{page}
    """
    prefix = "goods-page_"
    tail = call.data[len(prefix):]
    category_name, current_index = tail.rsplit("_", 1)
    current_index = int(current_index)

    # Get saved state
    data = await state.get_data()
    paginator_state = data.get('goods_paginator')

    # Determine back button target
    # Try to get from state if we came from categories
    categories_page = data.get('categories_last_viewed_page', 0)
    back_data = f"categories-page_{categories_page}"

    # Create paginator
    from bot.database.methods.lazy_queries import query_items_in_category
    from functools import partial

    query_func = partial(query_items_in_category, category_name)
    paginator = LazyPaginator(query_func, per_page=10, state=paginator_state)

    markup = await lazy_paginated_keyboard(
        paginator=paginator,
        item_text=lambda item: item,
        item_callback=lambda item: f"item_{item}_{category_name}_goods-page_{category_name}_{current_index}",
        page=current_index,
        back_cb=back_data,
        nav_cb_prefix=f"goods-page_{category_name}_",
    )

    await call.message.edit_text(localize("shop.goods.choose"), reply_markup=markup)

    # Update state
    await state.update_data(goods_paginator=paginator.get_state())


@router.callback_query(F.data.startswith('item_'))
async def item_info_callback_handler(call: CallbackQuery):
    """
    Show detailed information about the item.
    Format: item_{name}_{category}_goods-page_{category}_{page}
    """
    # Parse callback data
    callback_data = call.data[5:]  # Remove 'item_'

    # Extract item name, category and back data
    if '_goods-page_' in callback_data:
        # Split by the last occurrence of _goods-page_
        item_and_cat, back_page_data = callback_data.rsplit('_goods-page_', 1)
        # Now split item_and_cat to get item name and category
        parts = item_and_cat.rsplit('_', 1)
        if len(parts) == 2:
            item_name, category = parts
        else:
            item_name = item_and_cat
            category = ""
        back_data = f"goods-page_{back_page_data}"
    else:
        item_name = callback_data
        back_data = "shop"
        category = ""

    item_info_data = await get_item_info_cached(item_name)
    if not item_info_data:
        await call.answer(localize("shop.item.not_found"), show_alert=True)
        return

    # If couldn't extract category from callback, get it from item info
    if not category:
        category = item_info_data.get('category_name', '')

    quantity = await select_item_values_amount_cached(item_name)

    quantity_line = (
        localize("shop.item.quantity_unlimited")
        if check_value(item_name)
        else localize("shop.item.quantity_left", count=quantity)
    )

    markup = item_info(item_name, back_data)

    await call.message.edit_text(
        "\n".join([
            localize("shop.item.title", name=item_name),
            localize("shop.item.description", description=item_info_data["description"]),
            localize("shop.item.price", amount=item_info_data["price"], currency=EnvKeys.PAY_CURRENCY),
            quantity_line,
        ]),
        reply_markup=markup,
    )


@router.callback_query(F.data == "bought_items")
async def bought_items_callback_handler(call: CallbackQuery, state: FSMContext):
    """
    Show list of user's purchased items with lazy loading.
    """
    user_id = call.from_user.id

    # Create paginator for user's bought items
    query_func = partial(query_user_bought_items, user_id)
    paginator = LazyPaginator(query_func, per_page=10)

    markup = await lazy_paginated_keyboard(
        paginator=paginator,
        item_text=lambda item: item.item_name,
        item_callback=lambda item: f"bought-item:{item.id}:bought-goods-page_user_0",
        page=0,
        back_cb="profile",
        nav_cb_prefix="bought-goods-page_user_"
    )

    await call.message.edit_text(localize("purchases.title"), reply_markup=markup)

    # Save paginator state
    await state.update_data(bought_items_paginator=paginator.get_state())


@router.callback_query(F.data.startswith('bought-goods-page_'))
async def navigate_bought_items(call: CallbackQuery, state: FSMContext):
    """
    Pagination for user's purchased items with lazy loading.
    Format: 'bought-goods-page_{data}_{page}', where data = 'user' or user_id.
    """
    parts = call.data.split('_')
    if len(parts) < 3:
        await call.answer(localize("purchases.pagination.invalid"))
        return

    data_type = parts[1]
    try:
        current_index = int(parts[2])
    except ValueError:
        current_index = 0

    if data_type == 'user':
        user_id = call.from_user.id
        back_cb = 'profile'
        pre_back = f'bought-goods-page_user_{current_index}'
    else:
        user_id = int(data_type)
        back_cb = f'check-user_{data_type}'
        pre_back = f'bought-goods-page_{data_type}_{current_index}'

    # Get saved state
    data = await state.get_data()
    paginator_state = data.get('bought_items_paginator')

    # Create paginator with cached state
    query_func = partial(query_user_bought_items, user_id)
    paginator = LazyPaginator(query_func, per_page=10, state=paginator_state)

    markup = await lazy_paginated_keyboard(
        paginator=paginator,
        item_text=lambda item: item.item_name,
        item_callback=lambda item: f"bought-item:{item.id}:{pre_back}",
        page=current_index,
        back_cb=back_cb,
        nav_cb_prefix=f"bought-goods-page_{data_type}_"
    )

    await call.message.edit_text(localize("purchases.title"), reply_markup=markup)

    # Update state
    await state.update_data(bought_items_paginator=paginator.get_state())


@router.callback_query(F.data.startswith('bought-item:'))
async def bought_item_info_callback_handler(call: CallbackQuery):
    """
    Show details for a purchased item.
    """
    trash, item_id, back_data = call.data.split(':', 2)
    item = get_bought_item_info(item_id)
    if not item:
        await call.answer(localize("purchases.item.not_found"), show_alert=True)
        return

    text = "\n".join([
        localize("purchases.item.name", name=item["item_name"]),
        localize("purchases.item.price", amount=item["price"], currency=EnvKeys.PAY_CURRENCY),
        localize("purchases.item.datetime", dt=item["bought_datetime"]),
        localize("purchases.item.unique_id", uid=item["unique_id"]),
        localize("purchases.item.value", value=item["value"]),
    ])
    await call.message.edit_text(text, parse_mode='HTML', reply_markup=back(back_data))
