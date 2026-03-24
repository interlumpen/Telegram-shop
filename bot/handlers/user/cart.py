from decimal import Decimal

from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext

from bot.database.methods.create import add_to_cart
from bot.database.methods.read import get_cart_items, get_cart_count
from bot.database.methods.delete import remove_from_cart, clear_cart
from bot.database.methods.transactions import checkout_cart_transaction
from bot.keyboards.inline import back, simple_buttons
from bot.misc import EnvKeys
from bot.i18n import localize

router = Router()


async def _resolve_promo_price(price: Decimal, promo_code: str | None) -> Decimal | None:
    """Return discounted price if promo is valid, else None."""
    if not promo_code:
        return None
    from bot.database.methods.read import get_promo_code
    promo = await get_promo_code(promo_code)
    if not promo or not promo.get('is_active'):
        return None
    if promo['discount_type'] == 'percent':
        discount = price * Decimal(str(promo['discount_value'])) / 100
    else:
        discount = min(Decimal(str(promo['discount_value'])), price)
    return (price - discount).quantize(Decimal("0.01"))


async def _show_cart(call: CallbackQuery):
    """Shared logic: render cart view."""
    user_id = call.from_user.id
    items = await get_cart_items(user_id)

    if not items:
        await call.message.edit_text(
            localize("cart.title") + "\n\n" + localize("cart.empty"),
            reply_markup=back("profile"),
        )
        return

    from bot.database.methods.read import get_item_info
    lines = [localize("cart.title"), ""]
    real_total = Decimal(0)

    for item in items:
        info = await get_item_info(item['item_name'])
        if not info:
            lines.append(localize("cart.item", name=item['item_name'], price='?', currency=EnvKeys.PAY_CURRENCY))
            continue

        price = Decimal(str(info['price']))
        discounted = await _resolve_promo_price(price, item.get('promo_code'))

        if discounted is not None:
            lines.append(f"🏷 <b>{item['item_name']}</b> — <s>{price}</s> {discounted} {EnvKeys.PAY_CURRENCY} ({item['promo_code']})")
            real_total += discounted
        else:
            lines.append(localize("cart.item", name=item['item_name'], price=price, currency=EnvKeys.PAY_CURRENCY))
            real_total += price

    lines.append(localize("cart.total", total=real_total, currency=EnvKeys.PAY_CURRENCY))

    buttons = []
    for item in items:
        buttons.append((f"❌ {item['item_name']}", f"cart_remove:{item['id']}"))
    buttons.append((localize("btn.cart_checkout"), "cart_checkout"))
    buttons.append((localize("btn.cart_clear"), "cart_clear"))
    buttons.append((localize("btn.back"), "profile"))

    await call.message.edit_text(
        "\n".join(lines),
        reply_markup=simple_buttons(buttons),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "add_to_cart")
async def add_to_cart_handler(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    item_name = data.get('csrf_item')
    if not item_name:
        await call.answer(localize("cart.item_not_found"), show_alert=True)
        return

    promo_code = data.get('applied_promo')

    success, msg = await add_to_cart(call.from_user.id, item_name, promo_code=promo_code)
    if success:
        await call.answer(localize("cart.added", name=item_name))
    else:
        error_map = {
            "cart_full": localize("cart.full"),
            "item_not_found": localize("cart.item_not_found"),
        }
        await call.answer(error_map.get(msg, msg), show_alert=True)


@router.callback_query(F.data == "cart")
async def view_cart_handler(call: CallbackQuery, state: FSMContext):
    await _show_cart(call)


@router.callback_query(F.data.startswith("cart_remove:"))
async def remove_cart_item_handler(call: CallbackQuery, state: FSMContext):
    cart_item_id = int(call.data.split(":")[1])
    removed = await remove_from_cart(cart_item_id, user_id=call.from_user.id)
    if removed:
        await call.answer(localize("cart.removed"))
    else:
        await call.answer(localize("cart.item_not_found"), show_alert=True)
    await _show_cart(call)


@router.callback_query(F.data == "cart_clear")
async def clear_cart_handler(call: CallbackQuery, state: FSMContext):
    await clear_cart(call.from_user.id)
    await call.answer(localize("cart.cleared"))
    await _show_cart(call)


async def _calc_cart_total_with_promos(user_id: int) -> Decimal:
    """Calculate real cart total considering promo codes on each item."""
    from bot.database.methods.read import get_item_info
    items = await get_cart_items(user_id)
    total = Decimal(0)
    for item in items:
        info = await get_item_info(item['item_name'])
        if not info:
            continue
        price = Decimal(str(info['price']))
        discounted = await _resolve_promo_price(price, item.get('promo_code'))
        total += discounted if discounted is not None else price
    return total


@router.callback_query(F.data == "cart_checkout")
async def cart_checkout_handler(call: CallbackQuery, state: FSMContext):
    user_id = call.from_user.id
    count = await get_cart_count(user_id)
    total = await _calc_cart_total_with_promos(user_id)

    buttons = [
        (localize("btn.yes"), "cart_checkout_confirm"),
        (localize("btn.no"), "cart"),
    ]
    await call.message.edit_text(
        localize("cart.checkout_confirm", count=count, total=total, currency=EnvKeys.PAY_CURRENCY),
        reply_markup=simple_buttons(buttons),
    )


@router.callback_query(F.data == "cart_checkout_confirm")
async def cart_checkout_confirm_handler(call: CallbackQuery, state: FSMContext):
    user_id = call.from_user.id
    await call.answer(localize("shop.purchase.processing"))

    success, msg, results = await checkout_cart_transaction(user_id)

    if not success:
        reason_map = {
            "user_not_found": "User not found",
            "cart_empty": localize("cart.empty"),
            "cart_items_unavailable": localize("cart.items_unavailable"),
            "insufficient_funds": localize("shop.insufficient_funds"),
            "transaction_error": localize("errors.something_wrong"),
            "promo_expired_during_checkout": localize("cart.promo_expired"),
        }
        await call.message.edit_text(
            localize("cart.checkout_fail", reason=reason_map.get(msg, msg)),
            reply_markup=back("cart"),
        )
        return

    total = sum(r['price'] for r in results)
    username = call.from_user.username or call.from_user.first_name
    dt = results[0]['bought_datetime'] if results else ""

    # Save results in state for cart_receipt back navigation
    await state.update_data(cart_receipt_results=results, cart_receipt_total=float(total))

    buttons = []
    for r in results:
        buttons.append((f"📦 {r['item_name']}", f"bought-item:{r['bought_id']}:cart_receipt"))
    buttons.append((localize("btn.back"), "profile"))

    await call.message.edit_text(
        localize(
            "cart.checkout_receipt",
            count=len(results),
            total=total,
            currency=EnvKeys.PAY_CURRENCY,
            username=username,
            user_id=user_id,
            datetime=dt,
        ),
        parse_mode="HTML",
        reply_markup=simple_buttons(buttons),
    )

    from bot.database.methods.audit import log_audit
    await log_audit(
        "cart_checkout",
        user_id=user_id,
        resource_type="Cart",
        details=f"items={len(results)}, total={sum(r['price'] for r in results)}",
    )


@router.callback_query(F.data == "cart_receipt")
async def cart_receipt_handler(call: CallbackQuery, state: FSMContext):
    """Re-render the cart checkout receipt (back from bought-item detail)."""
    data = await state.get_data()
    results = data.get("cart_receipt_results")
    total = data.get("cart_receipt_total", 0)

    if not results:
        await call.message.edit_text(
            localize("cart.empty"),
            reply_markup=back("profile"),
        )
        return

    username = call.from_user.username or call.from_user.first_name
    dt = results[0].get("bought_datetime", "")

    buttons = []
    for r in results:
        buttons.append((f"📦 {r['item_name']}", f"bought-item:{r['bought_id']}:cart_receipt"))
    buttons.append((localize("btn.back"), "profile"))

    await call.message.edit_text(
        localize(
            "cart.checkout_receipt",
            count=len(results),
            total=total,
            currency=EnvKeys.PAY_CURRENCY,
            username=username,
            user_id=call.from_user.id,
            datetime=dt,
        ),
        parse_mode="HTML",
        reply_markup=simple_buttons(buttons),
    )
