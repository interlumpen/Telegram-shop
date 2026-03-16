from decimal import Decimal
from functools import partial

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest

from bot.database.methods import (
    get_bought_item_info, check_value, query_categories, query_user_bought_items, get_item_info_cached,
    select_item_values_amount_cached
)
from bot.database.methods.read import (
    get_item_avg_rating, has_purchased_item, validate_promo_for_item,
    get_user_review, invalidate_rating_cache, get_item_info,
)
from bot.database.methods.create import create_review
from bot.database.methods.lazy_queries import query_item_reviews
from bot.database.methods.transactions import redeem_balance_promo
from bot.database.methods.audit import log_audit
from bot.keyboards import item_info, back, lazy_paginated_keyboard
from bot.keyboards.inline import simple_buttons, rating_keyboard
from bot.i18n import localize
from bot.misc import EnvKeys, LazyPaginator
from bot.misc.metrics import get_metrics
from bot.states import ShopStates
from bot.states.review_state import ReviewFSM
from bot.states.promo_state import PromoFSM

router = Router()


# --- Shared helper: render item page ---

async def _render_item_page(target, state: FSMContext, item_name: str, back_data: str = None, user_id: int = None):
    """
    Render the item detail page with optional promo discount.
    `target` can be CallbackQuery or Message.
    """
    data = await state.get_data()
    if not back_data:
        back_data = data.get('item_back_data', 'gp_0')

    item_info_data = await get_item_info_cached(item_name)
    if not item_info_data:
        if isinstance(target, CallbackQuery):
            await target.answer(localize("shop.item.not_found"), show_alert=True)
        else:
            await target.answer(localize("shop.item.not_found"))
        return

    quantity = await select_item_values_amount_cached(item_name)
    quantity_line = (
        localize("shop.item.quantity_unlimited")
        if await check_value(item_name)
        else localize("shop.item.quantity_left", count=quantity)
    )

    reviews_enabled = EnvKeys.REVIEWS_ENABLED == "1"
    avg_rating = None
    review_count_val = 0
    purchased = False

    if reviews_enabled:
        avg_rating = await get_item_avg_rating(item_name)
        review_count_val = await query_item_reviews(item_name, count_only=True)
        if user_id:
            purchased = await has_purchased_item(user_id, item_name)

    applied_promo = data.get('applied_promo')

    # Build price line
    price = Decimal(str(item_info_data["price"]))
    if applied_promo:
        promo_data = data.get('applied_promo_data', {})
        if promo_data.get('discount_type') == 'percent':
            discount = price * Decimal(str(promo_data.get('discount_value', 0))) / 100
        else:
            discount = min(Decimal(str(promo_data.get('discount_value', 0))), price)
        discounted = (price - discount).quantize(Decimal("0.01"))
        price_line = localize(
            "shop.item.price_discounted",
            original=price, discounted=discounted,
            currency=EnvKeys.PAY_CURRENCY, code=applied_promo,
        )
    else:
        price_line = localize("shop.item.price", amount=price, currency=EnvKeys.PAY_CURRENCY)

    markup = item_info(
        item_name, back_data,
        avg_rating=avg_rating, review_count=review_count_val,
        has_purchased=purchased, applied_promo=applied_promo,
        reviews_enabled=reviews_enabled,
    )

    text_lines = [
        localize("shop.item.title", name=item_name),
        localize("shop.item.description", description=item_info_data["description"]),
        price_line,
        quantity_line,
    ]
    if reviews_enabled and avg_rating is not None:
        text_lines.append(localize("review.avg_rating", rating=avg_rating, count=review_count_val))

    text = "\n".join(text_lines)

    try:
        if hasattr(target, 'message') and hasattr(target.message, 'edit_text'):
            await target.message.edit_text(text, reply_markup=markup)
        else:
            await target.answer(text, reply_markup=markup)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise


# --- Shop / categories / items ---

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

    if idx < 0 or idx >= len(goods_page_items):
        await call.answer(localize("shop.item.not_found"), show_alert=True)
        return

    item_name = goods_page_items[idx]
    back_data = f"gp_{goods_page}"

    metrics = get_metrics()
    if metrics:
        metrics.track_conversion("purchase_funnel", "view_item", call.from_user.id)

    # Save item name and back_data in state
    await state.update_data(csrf_item=item_name, item_back_data=back_data)

    await _render_item_page(call, state, item_name, back_data, user_id=call.from_user.id)



# --- Promo Code Application ---

@router.callback_query(F.data == "apply_promo")
async def apply_promo_handler(call: CallbackQuery, state: FSMContext):
    await call.message.edit_text(localize("promo.enter_code"), reply_markup=back("back_to_item"))
    await state.update_data(awaiting_promo=True)


@router.callback_query(F.data == "remove_promo")
async def remove_promo_handler(call: CallbackQuery, state: FSMContext):
    await state.update_data(applied_promo=None, applied_promo_data=None)
    data = await state.get_data()
    item_name = data.get('csrf_item')
    if item_name:
        await _render_item_page(call, state, item_name, user_id=call.from_user.id)
    else:
        await call.answer(localize("promo.removed"))


@router.callback_query(F.data == "back_to_item")
async def back_to_item_handler(call: CallbackQuery, state: FSMContext):
    """Return to item page, preserving promo state."""
    data = await state.get_data()
    item_name = data.get('csrf_item')
    if not item_name:
        # Fallback
        await call.message.edit_text(
            localize("shop.item.not_found"),
            reply_markup=back("back_to_menu"),
        )
        return
    await state.update_data(awaiting_promo=False)
    await _render_item_page(call, state, item_name, user_id=call.from_user.id)


# --- Balance Promo Redemption (from profile) ---

@router.callback_query(F.data == "redeem_promo")
async def redeem_promo_handler(call: CallbackQuery, state: FSMContext):
    await call.message.edit_text(localize("promo.enter_redeem_code"), reply_markup=back("profile"))
    await state.set_state(PromoFSM.waiting_redeem_code)


@router.message(PromoFSM.waiting_redeem_code, F.text)
async def redeem_promo_code_handler(message: Message, state: FSMContext):
    code = (message.text or "").strip().upper()
    success, error_key, amount = await redeem_balance_promo(code, message.from_user.id)

    if success:
        await message.answer(
            localize("promo.balance_redeemed", code=code, amount=amount, currency=EnvKeys.PAY_CURRENCY),
            reply_markup=back("profile"),
        )
        await log_audit(
            "promo_redeem", user_id=message.from_user.id,
            resource_type="PromoCode", resource_id=code,
        )
    else:
        await message.answer(localize(error_key), reply_markup=back("profile"))

    await state.clear()


# --- Review Handlers ---

@router.callback_query(F.data.startswith("review:"))
async def start_review_handler(call: CallbackQuery, state: FSMContext):
    if EnvKeys.REVIEWS_ENABLED != "1":
        await call.answer(localize("review.disabled"), show_alert=True)
        return

    item_name = call.data.split(":", 1)[1]

    # Check if user purchased the item
    purchased = await has_purchased_item(call.from_user.id, item_name)
    if not purchased:
        await call.answer(localize("review.not_purchased"), show_alert=True)
        return

    # Check if already reviewed
    existing = await get_user_review(call.from_user.id, item_name)
    if existing:
        await call.answer(localize("review.already_exists"), show_alert=True)
        return

    await state.update_data(review_item_name=item_name)
    await call.message.edit_text(
        localize("review.prompt_rating", name=item_name),
        reply_markup=rating_keyboard(item_name),
    )
    await state.set_state(ReviewFSM.waiting_rating)


@router.callback_query(F.data.startswith("rating:"), ReviewFSM.waiting_rating)
async def receive_rating_handler(call: CallbackQuery, state: FSMContext):
    rating = int(call.data.split(":")[1])
    await state.update_data(review_rating=rating)

    buttons = [
        (localize("btn.skip_review_text"), "skip_review_text"),
        (localize("btn.back"), "back_to_menu"),
    ]
    await call.message.edit_text(
        localize("review.prompt_text"),
        reply_markup=simple_buttons(buttons),
    )
    await state.set_state(ReviewFSM.waiting_text)


@router.callback_query(F.data == "skip_review_text", ReviewFSM.waiting_text)
async def skip_review_text_handler(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    item_name = data.get('review_item_name')
    rating = data.get('review_rating')

    await create_review(call.from_user.id, item_name, rating)
    await invalidate_rating_cache(item_name)
    await call.message.edit_text(localize("review.created"), reply_markup=back("back_to_menu"))
    await state.clear()


@router.message(ReviewFSM.waiting_text, F.text)
async def receive_review_text_handler(message: Message, state: FSMContext):
    data = await state.get_data()
    item_name = data.get('review_item_name')
    rating = data.get('review_rating')
    text = (message.text or "")[:500].strip()

    await create_review(message.from_user.id, item_name, rating, text)
    await invalidate_rating_cache(item_name)
    await message.answer(localize("review.created"), reply_markup=back("back_to_menu"))
    await state.clear()


# --- Promo code text input (catch-all, must be AFTER state-specific message handlers) ---

@router.message(F.text)
async def promo_code_text_handler(message: Message, state: FSMContext):
    """Handle promo code text input when awaiting_promo is set."""
    data = await state.get_data()
    if not data.get('awaiting_promo'):
        return  # Not awaiting promo input — skip

    item_name = data.get('csrf_item')
    if not item_name:
        await state.update_data(awaiting_promo=False)
        return

    code = (message.text or "").strip().upper()
    valid, error_key, promo_data = await validate_promo_for_item(code, item_name, message.from_user.id)

    if not valid:
        await message.answer(localize(error_key), reply_markup=back("back_to_item"))
        await state.update_data(awaiting_promo=False)
        return

    # Store promo data for discounted price display
    await state.update_data(
        applied_promo=code,
        applied_promo_data={
            'discount_type': promo_data.get('discount_type'),
            'discount_value': str(promo_data.get('discount_value', 0)),
        },
        awaiting_promo=False,
    )

    # Re-render item page with discounted price
    await _render_item_page(message, state, item_name, user_id=message.from_user.id)


# --- View Reviews ---

@router.callback_query(F.data.startswith("reviews:"))
async def view_reviews_handler(call: CallbackQuery, state: FSMContext):
    if EnvKeys.REVIEWS_ENABLED != "1":
        await call.answer(localize("review.disabled"), show_alert=True)
        return

    parts = call.data.split(":")
    item_name = parts[1]
    page = int(parts[2]) if len(parts) > 2 else 0

    paginator = LazyPaginator(
        partial(query_item_reviews, item_name),
        per_page=5,
    )

    reviews = await paginator.get_page(page)
    total_pages = await paginator.get_total_pages()

    if not reviews:
        await call.message.edit_text(
            localize("review.list_empty"),
            reply_markup=back("back_to_item"),
        )
        return

    lines = [localize("review.list_title", name=item_name), ""]
    for r in reviews:
        if r.get('text'):
            lines.append(localize("review.item", rating=r['rating'], text=r['text'][:100]))
        else:
            lines.append(localize("review.item_no_text", rating=r['rating']))

    # Navigation
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    kb = InlineKeyboardBuilder()
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="◀️", callback_data=f"reviews:{item_name}:{page - 1}"))
    if total_pages > 1:
        nav_buttons.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(text="▶️", callback_data=f"reviews:{item_name}:{page + 1}"))
    if nav_buttons:
        kb.row(*nav_buttons)
    kb.row(InlineKeyboardButton(text=localize("btn.back"), callback_data="back_to_item"))

    await call.message.edit_text("\n".join(lines), reply_markup=kb.as_markup())


# --- Bought items ---

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
    item = await get_bought_item_info(int(item_id))
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
