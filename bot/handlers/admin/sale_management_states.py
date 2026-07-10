from datetime import datetime, timedelta, timezone
from decimal import Decimal

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message

from bot.database.models import Permission
from bot.database.methods import get_item_info_cached
from bot.database.methods.update import set_item_sale
from bot.database.methods.pricing import effective_price, coerce_sale_until
from bot.database.methods.audit import log_audit
from bot.keyboards.inline import back
from bot.filters import HasPermissionFilter
from bot.i18n import localize
from bot.states import SaleFSM

router = Router()


def _fmt_percent(value) -> str:
    """Render a discount percent without trailing zeros (20.00 -> '20')."""
    if value is None:
        return "0"
    return f"{Decimal(str(value)):g}"


@router.callback_query(F.data == 'manage_sale', HasPermissionFilter(permission=Permission.CATALOG_MANAGE))
async def manage_sale_callback_handler(call: CallbackQuery, state):
    """Start the sale management flow: ask for the item name."""
    await call.message.edit_text(localize('admin.sale.prompt.name'), reply_markup=back('goods_management'))
    await state.set_state(SaleFSM.waiting_item_name)


@router.message(SaleFSM.waiting_item_name, F.text)
async def sale_item_name(message: Message, state):
    """Validate the item and show its current sale status, then ask for percent."""
    item_name = message.text.strip()
    item = await get_item_info_cached(item_name)
    if not item:
        await message.answer(localize('admin.sale.not_found'), reply_markup=back('goods_management'))
        return

    _final, on_sale, _original = effective_price(item)
    if on_sale:
        until = coerce_sale_until(item.get('sale_until'))
        until_str = until.strftime('%Y-%m-%d %H:%M') if until else '-'
        status = localize('admin.sale.current.active',
                          percent=_fmt_percent(item.get('sale_percent')), until=until_str)
    else:
        status = localize('admin.sale.current.none')

    await state.update_data(sale_item_name=item_name)
    await message.answer(
        f"{status}\n\n{localize('admin.sale.prompt.percent')}",
        parse_mode='HTML',
        reply_markup=back('goods_management'),
    )
    await state.set_state(SaleFSM.waiting_percent)


@router.message(SaleFSM.waiting_percent, F.text)
async def sale_percent(message: Message, state):
    """Validate the percent. 0 removes the sale; otherwise ask for the duration."""
    text = message.text.strip()
    if not text.isdigit() or int(text) > 100:
        await message.answer(localize('admin.sale.percent.invalid'), reply_markup=back('goods_management'))
        return

    percent = int(text)
    data = await state.get_data()
    item_name = data.get('sale_item_name')

    if percent == 0:
        await set_item_sale(item_name, None, None)
        await message.answer(localize('admin.sale.disabled', name=item_name), reply_markup=back('goods_management'))
        admin_info = await message.bot.get_chat(message.from_user.id)
        await log_audit("set_item_sale", user_id=message.from_user.id, resource_type="Item",
                        resource_id=item_name, details=f"admin={admin_info.first_name}, disabled")
        await state.clear()
        return

    await state.update_data(sale_percent=percent)
    await message.answer(localize('admin.sale.prompt.days'), reply_markup=back('goods_management'))
    await state.set_state(SaleFSM.waiting_days)


@router.message(SaleFSM.waiting_days, F.text)
async def sale_days(message: Message, state):
    """Validate the duration, set the sale, and confirm."""
    text = message.text.strip()
    if not text.isdigit() or int(text) <= 0:
        await message.answer(localize('admin.sale.days.invalid'), reply_markup=back('goods_management'))
        return

    days = int(text)
    data = await state.get_data()
    item_name = data.get('sale_item_name')
    percent = data.get('sale_percent')

    sale_until = datetime.now(timezone.utc) + timedelta(days=days)
    ok = await set_item_sale(item_name, Decimal(percent), sale_until)
    if not ok:
        await message.answer(localize('admin.sale.not_found'), reply_markup=back('goods_management'))
        await state.clear()
        return

    until_str = sale_until.strftime('%Y-%m-%d %H:%M')
    await message.answer(
        localize('admin.sale.success', percent=percent, name=item_name, until=until_str),
        parse_mode='HTML',
        reply_markup=back('goods_management'),
    )
    admin_info = await message.bot.get_chat(message.from_user.id)
    await log_audit("set_item_sale", user_id=message.from_user.id, resource_type="Item", resource_id=item_name,
                    details=f"admin={admin_info.first_name}, percent={percent}, until={sale_until.isoformat()}")
    await state.clear()
