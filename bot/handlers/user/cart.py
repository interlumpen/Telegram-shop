from collections import Counter
from decimal import Decimal

from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest

from bot.database.methods.create import add_to_cart, CART_MAX_QTY_PER_ITEM
from bot.database.methods.read import get_cart_items, get_cart_count, validate_promo_for_item
from bot.database.methods.update import set_cart_item_quantity
from bot.database.methods.delete import remove_from_cart, clear_cart
from bot.database.methods.transactions import checkout_cart_transaction
from bot.keyboards.inline import back, simple_buttons, cart_keyboard
from bot.misc import EnvKeys
from bot.i18n import localize

router = Router()

# A checkout can deliver hundreds of units; the receipt only ever shows this many, then defers to the paginated purchases list.
RECEIPT_MAX_BUTTONS = 10


async def _resolve_promo_price(price: Decimal, promo_code: str | None, item_name: str,
                               user_id: int, quantity: int = 1) -> Decimal | None:
    """Return the discounted line total, or None if the promo does not apply.

    A percent promo scales with quantity; a fixed promo comes off the line once.
    """
    if not promo_code:
        return None

    valid, _err, promo = await validate_promo_for_item(promo_code, item_name, user_id)
    if not valid:
        return None

    if promo['discount_type'] == 'percent':
        discount = price * Decimal(str(promo['discount_value'])) / 100
        unit = price - discount
        return (unit * quantity).quantize(Decimal("0.01"))

    line = price * quantity
    discount = min(Decimal(str(promo['discount_value'])), line)
    return (line - discount).quantize(Decimal("0.01"))


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

    from bot.database.methods.read import get_items_info
    from bot.database.methods import effective_price
    info_map = await get_items_info([item['item_name'] for item in items])
    lines = [localize("cart.title"), ""]
    real_total = Decimal(0)

    for item in items:
        info = info_map.get(item['item_name'])
        qty = item['quantity']
        if not info:
            lines.append(localize(
                "cart.item", name=item['item_name'], qty=qty,
                price='?', currency=EnvKeys.PAY_CURRENCY,
            ))
            continue

        # Sale price is the base; a promo code (if any) stacks on top of it.
        base_price, on_sale, original = effective_price(info)
        discounted = await _resolve_promo_price(
            base_price, item.get('promo_code'), item['item_name'], user_id, qty,
        )

        if discounted is not None:
            line_total = discounted
            lines.append(localize(
                "cart.item_promo", name=item['item_name'], qty=qty,
                original=(original * qty).quantize(Decimal("0.01")), price=line_total,
                currency=EnvKeys.PAY_CURRENCY, code=item['promo_code'],
            ))
        elif item.get('promo_code'):
            line_total = (base_price * qty).quantize(Decimal("0.01"))
            lines.append(localize(
                "cart.item_promo_invalid", name=item['item_name'], qty=qty,
                price=line_total, currency=EnvKeys.PAY_CURRENCY,
                code=item['promo_code'],
            ))
        elif on_sale:
            line_total = (base_price * qty).quantize(Decimal("0.01"))
            lines.append(localize(
                "cart.item_sale", name=item['item_name'], qty=qty,
                original=(original * qty).quantize(Decimal("0.01")), price=line_total,
                currency=EnvKeys.PAY_CURRENCY,
            ))
        else:
            line_total = (base_price * qty).quantize(Decimal("0.01"))
            lines.append(localize(
                "cart.item", name=item['item_name'], qty=qty,
                price=line_total, currency=EnvKeys.PAY_CURRENCY,
            ))
        real_total += line_total

    lines.append(localize("cart.total", total=real_total, currency=EnvKeys.PAY_CURRENCY))

    try:
        await call.message.edit_text(
            "\n".join(lines),
            reply_markup=cart_keyboard(items),
            parse_mode="HTML",
        )
    except TelegramBadRequest as e:
        # Stepping quantity up then back down re-renders an identical message.
        if "message is not modified" not in str(e):
            raise


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
            "cart_qty_max": localize("cart.qty_max", max=CART_MAX_QTY_PER_ITEM),
            "cart_conflict": localize("errors.something_wrong"),
            "invalid_quantity": localize("errors.something_wrong"),
        }
        await call.answer(error_map.get(msg, msg), show_alert=True)


@router.callback_query(F.data.startswith("cart_qty:"))
async def cart_qty_handler(call: CallbackQuery, state: FSMContext):
    """Step a cart line's quantity up or down. Format: cart_qty:{id}:{delta}"""
    parts = call.data.split(":")
    cart_item_id = int(parts[1])
    delta = int(parts[2])

    ok, code, _new_qty = await set_cart_item_quantity(cart_item_id, call.from_user.id, delta)
    if not ok:
        error_map = {
            "item_not_found": localize("cart.item_not_found"),
            "cart_qty_max": localize("cart.qty_max", max=CART_MAX_QTY_PER_ITEM),
        }
        await call.answer(error_map.get(code, code), show_alert=True)
    elif code == "removed":
        await call.answer(localize("cart.removed"))
    else:
        await call.answer()

    await _show_cart(call)


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


def _receipt_keyboard(results: list[dict]) -> InlineKeyboardMarkup:
    """Build the receipt's per-unit buttons, capped.
    """
    per_name = Counter(r['item_name'] for r in results)
    shown = Counter()

    buttons = []
    for r in results[:RECEIPT_MAX_BUTTONS]:
        name = r['item_name']
        shown[name] += 1
        # Several units of one position would otherwise be indistinguishable.
        label = f"📦 {name}" if per_name[name] == 1 else f"📦 {name} ({shown[name]})"
        buttons.append((label, f"bought-item:{r['bought_id']}:cart_receipt"))

    if len(results) > RECEIPT_MAX_BUTTONS:
        buttons.append((localize("btn.cart_receipt_all"), "bought_items"))
    buttons.append((localize("btn.back"), "profile"))
    return simple_buttons(buttons)


def _slim_receipt(results: list[dict]) -> list[dict]:
    """Drop the delivered secret before the receipt goes into FSM storage.

    Only bought_id / item_name / bought_datetime are needed to re-render, and
    FSM state is serialised into Redis when it is enabled.
    """
    return [
        {
            "item_name": r["item_name"],
            "bought_id": r["bought_id"],
            "bought_datetime": r["bought_datetime"],
            "price": r["price"],
        }
        for r in results
    ]


def _receipt_total(results: list[dict]) -> Decimal:
    """Sum a checkout's per-unit prices back into the line total.
    """
    return sum(
        (Decimal(str(r['price'])) for r in results), Decimal(0)
    ).quantize(Decimal("0.01"))


async def _calc_cart_total_with_promos(user_id: int) -> Decimal:
    """Calculate real cart total considering sales and promo codes on each item."""
    from bot.database.methods.read import get_items_info
    from bot.database.methods import effective_price
    items = await get_cart_items(user_id)
    info_map = await get_items_info([item['item_name'] for item in items])
    total = Decimal(0)
    for item in items:
        info = info_map.get(item['item_name'])
        if not info:
            continue
        qty = item['quantity']
        base_price, _on_sale, _original = effective_price(info)
        discounted = await _resolve_promo_price(
            base_price, item.get('promo_code'), item['item_name'], user_id, qty,
        )
        total += discounted if discounted is not None else (base_price * qty).quantize(Decimal("0.01"))
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
            "out_of_stock": localize("cart.out_of_stock"),
            "insufficient_funds": localize("shop.insufficient_funds"),
            "transaction_error": localize("errors.something_wrong"),
            "promo_expired_during_checkout": localize("cart.promo_expired"),
        }
        await call.message.edit_text(
            localize("cart.checkout_fail", reason=reason_map.get(msg, msg)),
            reply_markup=back("cart"),
        )
        return

    total = _receipt_total(results)
    username = call.from_user.username or call.from_user.first_name
    dt = results[0]['bought_datetime'] if results else ""

    # Save results in state for cart_receipt back navigation
    await state.update_data(
        cart_receipt_results=_slim_receipt(results),
        cart_receipt_total=str(total),
    )

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
        reply_markup=_receipt_keyboard(results),
    )

    from bot.database.methods.audit import log_audit
    await log_audit(
        "cart_checkout",
        user_id=user_id,
        resource_type="Cart",
        details=f"items={len(results)}, total={total}",
    )


@router.callback_query(F.data == "cart_receipt")
async def cart_receipt_handler(call: CallbackQuery, state: FSMContext):
    """Re-render the cart checkout receipt (back from bought-item detail)."""
    data = await state.get_data()
    results = data.get("cart_receipt_results")
    total = data.get("cart_receipt_total") or (_receipt_total(results) if results else 0)

    if not results:
        await call.message.edit_text(
            localize("cart.empty"),
            reply_markup=back("profile"),
        )
        return

    username = call.from_user.username or call.from_user.first_name
    dt = results[0].get("bought_datetime", "")

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
        reply_markup=_receipt_keyboard(results),
    )
