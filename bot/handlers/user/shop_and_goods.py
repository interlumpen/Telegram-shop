from decimal import Decimal
from functools import partial
from html import escape as html_escape

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest

from bot.database.methods import (
    get_bought_item_info, check_value, query_categories, query_user_bought_items, get_item_info_cached,
    select_item_values_amount_cached, effective_price
)
from bot.database.methods.read import (
    get_item_avg_rating, has_purchased_item, validate_promo_for_item,
    get_user_review, invalidate_rating_cache, get_item_info, is_subscribed_to_stock,
)
from bot.database.methods.create import create_review, subscribe_to_stock
from bot.database.methods.delete import unsubscribe_from_stock
from bot.database.methods.lazy_queries import query_item_reviews, query_goods_search
from bot.database.methods.transactions import redeem_balance_promo
from bot.database.methods.audit import log_audit
from bot.keyboards import item_info, back, lazy_paginated_keyboard
from bot.keyboards.inline import simple_buttons, rating_keyboard
from aiogram.types import InlineKeyboardButton
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
    is_infinite = await check_value(item_name)
    quantity_line = (
        localize("shop.item.quantity_unlimited")
        if is_infinite
        else localize("shop.item.quantity_left", count=quantity)
    )

    out_of_stock = (not is_infinite) and quantity == 0
    subscribed = bool(
        out_of_stock and user_id and await is_subscribed_to_stock(user_id, item_name)
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

    # Build price line. Sale price (if any) is the base; a promo stacks on top.
    sale_price, on_sale, original_price = effective_price(item_info_data)
    price = sale_price
    if applied_promo:
        promo_data = data.get('applied_promo_data', {})
        if promo_data.get('discount_type') == 'percent':
            discount = price * Decimal(str(promo_data.get('discount_value', 0))) / 100
        else:
            discount = min(Decimal(str(promo_data.get('discount_value', 0))), price)
        discounted = (price - discount).quantize(Decimal("0.01"))
        price_line = localize(
            "shop.item.price_discounted",
            original=original_price, discounted=discounted,
            currency=EnvKeys.PAY_CURRENCY, code=applied_promo,
        )
    elif on_sale:
        percent = (Decimal(str(item_info_data.get("sale_percent") or 0))).quantize(Decimal("1"))
        price_line = localize(
            "shop.item.price_sale",
            original=original_price, sale=sale_price,
            currency=EnvKeys.PAY_CURRENCY, percent=percent,
        )
    else:
        price_line = localize("shop.item.price", amount=price, currency=EnvKeys.PAY_CURRENCY)

    markup = item_info(
        item_name, back_data,
        avg_rating=avg_rating, review_count=review_count_val,
        has_purchased=purchased, applied_promo=applied_promo,
        reviews_enabled=reviews_enabled,
        out_of_stock=out_of_stock, subscribed=subscribed,
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

async def _show_categories_page(call: CallbackQuery, state: FSMContext, page: int):
    """Render one page of the category list (shared by the shop entry + paginate handlers)."""
    paginator_state = (await state.get_data()).get('categories_paginator') if page > 0 else None
    paginator = LazyPaginator(query_categories, per_page=10, state=paginator_state)

    # Pre-fetch page items to build the index map used by the item_callback.
    page_items = await paginator.get_page(page)
    items_index = {cat: idx for idx, cat in enumerate(page_items)}

    markup = await lazy_paginated_keyboard(
        paginator=paginator,
        item_text=lambda cat: cat,
        item_callback=lambda cat: f"cat:{items_index[cat]}:{page}",
        page=page,
        back_cb="back_to_menu",
        nav_cb_prefix="categories-page_",
        extra_rows=[[InlineKeyboardButton(
            text=localize("btn.search"), callback_data="shop_search",
        )]],
    )

    await call.message.edit_text(localize("shop.categories.title"), reply_markup=markup)
    await state.update_data(
        categories_paginator=paginator.get_state(),
        category_page_items=list(page_items),
    )


@router.callback_query(F.data == "shop")
async def shop_callback_handler(call: CallbackQuery, state: FSMContext):
    """Show list of shop categories with lazy loading."""
    metrics = get_metrics()
    if metrics:
        metrics.track_conversion("purchase_funnel", "view_shop", call.from_user.id)

    await _show_categories_page(call, state, 0)
    await state.set_state(ShopStates.viewing_categories)


@router.callback_query(F.data.startswith('categories-page_'))
async def navigate_categories(call: CallbackQuery, state: FSMContext):
    """Pagination across shop categories with cache."""
    parts = call.data.split('_', 1)
    page = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    await _show_categories_page(call, state, page)


async def _show_goods_page(call: CallbackQuery, state: FSMContext,
                           category_name: str, cat_page: int, page: int):
    """Render one page of goods inside a category (shared by category-open + paginate)."""
    from bot.database.methods.lazy_queries import query_items_in_category

    paginator_state = (await state.get_data()).get('goods_paginator') if page > 0 else None
    paginator = LazyPaginator(partial(query_items_in_category, category_name), per_page=10, state=paginator_state)

    page_items = await paginator.get_page(page)
    items_index = {item: i for i, item in enumerate(page_items)}

    markup = await lazy_paginated_keyboard(
        paginator=paginator,
        item_text=lambda item: item,
        item_callback=lambda item: f"itm:{items_index[item]}:{page}",
        page=page,
        back_cb=f"categories-page_{cat_page}",
        nav_cb_prefix="gp_",
    )

    await call.message.edit_text(localize("shop.goods.choose"), reply_markup=markup)
    await state.update_data(
        goods_paginator=paginator.get_state(),
        current_category=category_name,
        goods_page_items=list(page_items),
        categories_last_viewed_page=cat_page,
    )
    await state.set_state(ShopStates.viewing_goods)


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

    await _show_goods_page(call, state, category_page_items[idx], cat_page, 0)


@router.callback_query(F.data.startswith('gp_'), ShopStates.viewing_goods)
async def navigate_goods(call: CallbackQuery, state: FSMContext):
    """
    Pagination for items inside selected category.
    Format: gp_{page}
    """
    page = int(call.data[3:])
    data = await state.get_data()
    await _show_goods_page(
        call, state,
        data.get('current_category', ''),
        data.get('categories_last_viewed_page', 0),
        page,
    )


async def _open_item_from_index(call: CallbackQuery, state: FSMContext,
                                list_key: str, idx: int, back_data: str):
    """Open an item card by its index into an FSM-stored page list.

    Shared by the category and the search flows
    """
    data = await state.get_data()
    page_items = data.get(list_key, [])

    if idx < 0 or idx >= len(page_items):
        await call.answer(localize("shop.item.not_found"), show_alert=True)
        return

    item_name = page_items[idx]

    metrics = get_metrics()
    if metrics:
        metrics.track_conversion("purchase_funnel", "view_item", call.from_user.id)

    # Save item name and back_data in state
    await state.update_data(csrf_item=item_name, item_back_data=back_data)

    await _render_item_page(call, state, item_name, back_data, user_id=call.from_user.id)


@router.callback_query(F.data.startswith('itm:'))
async def item_info_callback_handler(call: CallbackQuery, state: FSMContext):
    """
    Show detailed information about the item.
    Format: itm:{index}:{page}
    """
    parts = call.data.split(':')
    idx = int(parts[1])
    goods_page = int(parts[2]) if len(parts) > 2 else 0

    await _open_item_from_index(call, state, 'goods_page_items', idx, f"gp_{goods_page}")


# --- Catalog search ---

async def _show_search_page(target, state: FSMContext, query: str, page: int):
    """Render one page of search results. `target` is a CallbackQuery or Message."""
    paginator_state = (await state.get_data()).get('search_paginator') if page > 0 else None
    paginator = LazyPaginator(
        partial(query_goods_search, query), per_page=10, state=paginator_state,
    )

    page_items = await paginator.get_page(page)
    safe_query = html_escape(query, quote=False)

    async def _render(text, markup):
        if isinstance(target, CallbackQuery):
            await target.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
        else:
            await target.answer(text, reply_markup=markup, parse_mode="HTML")

    if not page_items and page == 0:
        await _render(localize("shop.search.empty", query=safe_query), back("shop"))
        await state.set_state(None)
        return

    items_index = {item: i for i, item in enumerate(page_items)}
    markup = await lazy_paginated_keyboard(
        paginator=paginator,
        item_text=lambda item: item,
        item_callback=lambda item: f"sitm:{items_index[item]}:{page}",
        page=page,
        back_cb="shop",
        nav_cb_prefix="sp_",
    )

    total = await paginator.get_total_count()
    await _render(localize("shop.search.results", query=safe_query, count=total), markup)

    await state.update_data(
        search_paginator=paginator.get_state(),
        search_query=query,
        search_page_items=list(page_items),
    )
    await state.set_state(ShopStates.viewing_search_results)


@router.callback_query(F.data == "shop_search")
async def shop_search_handler(call: CallbackQuery, state: FSMContext):
    """Prompt for a search query."""
    await call.message.edit_text(localize("shop.search.prompt"), reply_markup=back("shop"))
    await state.set_state(ShopStates.waiting_search_query)


@router.message(ShopStates.waiting_search_query, F.text)
async def receive_search_query_handler(message: Message, state: FSMContext):
    query = (message.text or "").strip()

    if len(query) < 2 or len(query) > 64:
        # Stay in the state so the user can just retype.
        await message.answer(localize("shop.search.too_short"), reply_markup=back("shop"))
        return

    await _show_search_page(message, state, query, 0)


@router.callback_query(F.data.startswith('sp_'), ShopStates.viewing_search_results)
async def navigate_search(call: CallbackQuery, state: FSMContext):
    """Pagination across search results. Format: sp_{page}"""
    page = int(call.data[3:])
    data = await state.get_data()
    await _show_search_page(call, state, data.get('search_query', ''), page)


@router.callback_query(F.data.startswith('sitm:'))
async def search_item_info_handler(call: CallbackQuery, state: FSMContext):
    """
    Open an item from the search results.
    Format: sitm:{index}:{page}

    A separate namespace from itm:/gp_ because navigate_goods re-derives its page
    from current_category, which search results do not have.
    """
    parts = call.data.split(':')
    idx = int(parts[1])
    page = int(parts[2]) if len(parts) > 2 else 0

    await _open_item_from_index(call, state, 'search_page_items', idx, f"sp_{page}")



# --- Restock notifications ---

@router.callback_query(F.data == "sub_stock")
async def subscribe_stock_handler(call: CallbackQuery, state: FSMContext):
    """Subscribe to the restock notification for the item on screen."""
    item_name = (await state.get_data()).get('csrf_item')
    if not item_name:
        await call.answer(localize("shop.item.not_found"), show_alert=True)
        return

    ok, _code = await subscribe_to_stock(call.from_user.id, item_name)
    await call.answer(localize("stock.subscribed" if ok else "errors.something_wrong"))
    await _render_item_page(call, state, item_name, user_id=call.from_user.id)


@router.callback_query(F.data == "unsub_stock")
async def unsubscribe_stock_handler(call: CallbackQuery, state: FSMContext):
    """Cancel the restock notification for the item on screen."""
    item_name = (await state.get_data()).get('csrf_item')
    if not item_name:
        await call.answer(localize("shop.item.not_found"), show_alert=True)
        return

    await unsubscribe_from_stock(call.from_user.id, item_name)
    await call.answer(localize("stock.unsubscribed"))
    await _render_item_page(call, state, item_name, user_id=call.from_user.id)


# --- Promo Code Application ---

async def _leave_promo_input(state: FSMContext) -> None:
    """Put back the browsing state that the promo prompt replaced.

    The item card's Back button is `gp_{page}` / `sp_{page}`, and both
    navigate_goods and navigate_search are state-filtered. Returning to
    state=None instead of where we came from leaves that button dead.
    """
    data = await state.get_data()
    await state.set_state(data.get('pre_promo_state'))


@router.callback_query(F.data == "apply_promo")
async def apply_promo_handler(call: CallbackQuery, state: FSMContext):
    await call.message.edit_text(localize("promo.enter_code"), reply_markup=back("back_to_item"))
    await state.update_data(pre_promo_state=await state.get_state())
    await state.set_state(PromoFSM.waiting_item_code)


@router.message(PromoFSM.waiting_item_code, F.text)
async def promo_code_text_handler(message: Message, state: FSMContext):
    """Apply a promo code typed on an item page."""
    data = await state.get_data()
    item_name = data.get('csrf_item')

    await _leave_promo_input(state)

    if not item_name:
        await message.answer(localize("shop.item.not_found"), reply_markup=back("back_to_menu"))
        return

    code = (message.text or "").strip().upper()
    valid, error_key, promo_data = await validate_promo_for_item(code, item_name, message.from_user.id)

    if not valid:
        await message.answer(localize(error_key), reply_markup=back("back_to_item"))
        return

    # Store promo data for discounted price display
    await state.update_data(
        applied_promo=code,
        applied_promo_data={
            'discount_type': promo_data.get('discount_type'),
            'discount_value': str(promo_data.get('discount_value', 0)),
        },
    )

    # Re-render item page with discounted price
    await _render_item_page(message, state, item_name, user_id=message.from_user.id)


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
    await _leave_promo_input(state)
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

    lines = [localize("review.list_title", name=html_escape(item_name, quote=False)), ""]
    for r in reviews:
        if r.get('text'):
            lines.append(localize(
                "review.item", rating=r['rating'],
                text=html_escape(r['text'][:100], quote=False),
            ))
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
        nav_buttons.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="dummy_button"))
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
