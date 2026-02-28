from functools import partial

from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest

from bot.database.methods import (
    get_bought_item_info, check_value, query_categories, query_user_bought_items, get_item_info_cached,
    select_item_values_amount_cached
)
from bot.keyboards import item_info, back, lazy_paginated_keyboard
from bot.i18n import localize
from bot.misc import EnvKeys, LazyPaginator
from bot.misc.metrics import get_metrics
from bot.states import ShopStates

router = Router()


@router.callback_query(F.data == "shop")
async def shop_callback_handler(call: CallbackQuery, state: FSMContext):
    """
    Show list of shop categories with lazy loading.
    """
    metrics = get_metrics()
    if metrics:
        metrics.track_conversion("purchase_funnel", "view_shop", call.from_user.id)

    paginator = LazyPaginator(query_categories, per_page=10)

    # Pre-fetch page items to build index map and store in state
    page_items = await paginator.get_page(0)
    items_index = {cat: idx for idx, cat in enumerate(page_items)}

    markup = await lazy_paginated_keyboard(
        paginator=paginator,
        item_text=lambda cat: cat,
        item_callback=lambda cat: f"cat:{items_index[cat]}:{0}",
        page=0,
        back_cb="back_to_menu",
        nav_cb_prefix="categories-page_",
    )

    await call.message.edit_text(localize("shop.categories.title"), reply_markup=markup)

    await state.update_data(
        categories_paginator=paginator.get_state(),
        category_page_items=list(page_items),
    )
    await state.set_state(ShopStates.viewing_categories)


@router.callback_query(F.data.startswith('categories-page_'))
async def navigate_categories(call: CallbackQuery, state: FSMContext):
    """
    Pagination across shop categories with cache.
    """
    parts = call.data.split('_', 1)
    page = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0

    data = await state.get_data()
    paginator_state = data.get('categories_paginator')

    paginator = LazyPaginator(
        query_categories,
        per_page=10,
        state=paginator_state
    )

    # Pre-fetch page items to build index map and store in state
    page_items = await paginator.get_page(page)
    items_index = {cat: idx for idx, cat in enumerate(page_items)}

    markup = await lazy_paginated_keyboard(
        paginator=paginator,
        item_text=lambda cat: cat,
        item_callback=lambda cat: f"cat:{items_index[cat]}:{page}",
        page=page,
        back_cb="back_to_menu",
        nav_cb_prefix="categories-page_"
    )

    await call.message.edit_text(localize('shop.categories.title'), reply_markup=markup)

    await state.update_data(
        categories_paginator=paginator.get_state(),
        category_page_items=list(page_items),
    )


@router.callback_query(F.data.startswith('cat:'))
async def items_list_callback_handler(call: CallbackQuery, state: FSMContext):
    """
    Show items of selected category.
    Parse index and page from cat:{index}:{page}, look up category name from state.
    """
    parts = call.data.split(':')
    idx = int(parts[1])
    cat_page = int(parts[2]) if len(parts) > 2 else 0

    data = await state.get_data()
    category_page_items = data.get('category_page_items', [])

    if idx < 0 or idx >= len(category_page_items):
        await call.answer(localize("shop.item.not_found"), show_alert=True)
        return

    category_name = category_page_items[idx]
    back_data = f"categories-page_{cat_page}"

    from bot.database.methods.lazy_queries import query_items_in_category

    query_func = partial(query_items_in_category, category_name)
    paginator = LazyPaginator(query_func, per_page=10)

    # Pre-fetch page items to build index map and store in state
    page_items = await paginator.get_page(0)
    items_index = {item: i for i, item in enumerate(page_items)}

    markup = await lazy_paginated_keyboard(
        paginator=paginator,
        item_text=lambda item: item,
        item_callback=lambda item: f"itm:{items_index[item]}:0",
        page=0,
        back_cb=back_data,
        nav_cb_prefix="gp_",
    )

    await call.message.edit_text(localize("shop.goods.choose"), reply_markup=markup)

    await state.update_data(
        goods_paginator=paginator.get_state(),
        current_category=category_name,
        goods_page_items=list(page_items),
    )
    await state.set_state(ShopStates.viewing_goods)


@router.callback_query(F.data.startswith('gp_'), ShopStates.viewing_goods)
async def navigate_goods(call: CallbackQuery, state: FSMContext):
    """
    Pagination for items inside selected category.
    Format: gp_{page}
    """
    current_index = int(call.data[3:])

    data = await state.get_data()
    paginator_state = data.get('goods_paginator')
    category_name = data.get('current_category', '')

    categories_page = data.get('categories_last_viewed_page', 0)
    back_data = f"categories-page_{categories_page}"

    from bot.database.methods.lazy_queries import query_items_in_category

    query_func = partial(query_items_in_category, category_name)
    paginator = LazyPaginator(query_func, per_page=10, state=paginator_state)

    # Pre-fetch page items to build index map and store in state
    page_items = await paginator.get_page(current_index)
    items_index = {item: i for i, item in enumerate(page_items)}

    markup = await lazy_paginated_keyboard(
        paginator=paginator,
        item_text=lambda item: item,
        item_callback=lambda item: f"itm:{items_index[item]}:{current_index}",
        page=current_index,
        back_cb=back_data,
        nav_cb_prefix="gp_",
    )

    await call.message.edit_text(localize("shop.goods.choose"), reply_markup=markup)

    await state.update_data(
        goods_paginator=paginator.get_state(),
        goods_page_items=list(page_items),
    )


@router.callback_query(F.data.startswith('itm:'))
async def item_info_callback_handler(call: CallbackQuery, state: FSMContext):
    """
    Show detailed information about the item.
    Format: itm:{index}:{page}
    """
    parts = call.data.split(':')
    idx = int(parts[1])
    goods_page = int(parts[2]) if len(parts) > 2 else 0

    data = await state.get_data()
    goods_page_items = data.get('goods_page_items', [])
    category = data.get('current_category', '')

    if idx < 0 or idx >= len(goods_page_items):
        await call.answer(localize("shop.item.not_found"), show_alert=True)
        return

    item_name = goods_page_items[idx]
    back_data = f"gp_{goods_page}"

    item_info_data = await get_item_info_cached(item_name)
    if not item_info_data:
        await call.answer(localize("shop.item.not_found"), show_alert=True)
        return

    metrics = get_metrics()
    if metrics:
        metrics.track_conversion("purchase_funnel", "view_item", call.from_user.id)

    if not category:
        category = item_info_data.get('category_name', '')

    quantity = await select_item_values_amount_cached(item_name)

    quantity_line = (
        localize("shop.item.quantity_unlimited")
        if check_value(item_name)
        else localize("shop.item.quantity_left", count=quantity)
    )

    markup = item_info(item_name, back_data)

    # Save item name in state to verify intent on purchase
    await state.update_data(csrf_item=item_name)

    try:
        await call.message.edit_text(
            "\n".join([
                localize("shop.item.title", name=item_name),
                localize("shop.item.description", description=item_info_data["description"]),
                localize("shop.item.price", amount=item_info_data["price"], currency=EnvKeys.PAY_CURRENCY),
                quantity_line,
            ]),
            reply_markup=markup,
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise


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
