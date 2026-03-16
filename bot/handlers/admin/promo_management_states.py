from datetime import datetime, timezone

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.database.models import Permission
from bot.database.methods.create import create_promo_code
from bot.database.methods.delete import delete_promo_code
from bot.database.methods.update import toggle_promo_code
from bot.database.methods.lazy_queries import query_promo_codes
from bot.database.methods.read import get_promo_code, check_category, get_item_info
from bot.database.methods.audit import log_audit
from bot.filters import HasPermissionFilter
from bot.keyboards.inline import back, simple_buttons, lazy_paginated_keyboard
from bot.misc import LazyPaginator
from bot.i18n import localize
from bot.states import PromoFSM

router = Router()


# --- Promo list ---

@router.callback_query(F.data == "promo_mgmt", HasPermissionFilter(permission=Permission.PROMO_MANAGE))
async def promo_management_handler(call: CallbackQuery, state: FSMContext):
    paginator = LazyPaginator(query_promo_codes, per_page=10)
    page_items = await paginator.get_page(0)

    if not page_items:
        buttons = [
            (localize("admin.promo.create"), "promo_create"),
            (localize("btn.back"), "console"),
        ]
        await call.message.edit_text(
            localize("admin.promo.title") + "\n\n" + localize("admin.promo.list_empty"),
            reply_markup=simple_buttons(buttons),
        )
        await state.clear()
        return

    markup = await lazy_paginated_keyboard(
        paginator=paginator,
        item_text=lambda p: f"{'✅' if p['is_active'] else '⛔'} {p['code']} ({p['current_uses']}/{p['max_uses'] or '∞'})",
        item_callback=lambda p: f"promo_v_{p['id']}",
        page=0,
        back_cb=None,
        nav_cb_prefix="promos-page_",
    )

    # Rebuild: add Create, then Back (back always last)
    kb = InlineKeyboardBuilder()
    kb.attach(InlineKeyboardBuilder.from_markup(markup))
    kb.row(InlineKeyboardButton(text=localize("admin.promo.create"), callback_data="promo_create"))
    kb.row(InlineKeyboardButton(text=localize("btn.back"), callback_data="console"))
    markup = kb.as_markup()

    await call.message.edit_text(localize("admin.promo.title"), reply_markup=markup)
    await state.update_data(promo_paginator=paginator.get_state())


@router.callback_query(F.data.startswith("promos-page_"), HasPermissionFilter(permission=Permission.PROMO_MANAGE))
async def navigate_promos(call: CallbackQuery, state: FSMContext):
    page = int(call.data.split("_", 1)[1])
    data = await state.get_data()
    paginator = LazyPaginator(query_promo_codes, per_page=10, state=data.get('promo_paginator'))

    markup = await lazy_paginated_keyboard(
        paginator=paginator,
        item_text=lambda p: f"{'✅' if p['is_active'] else '⛔'} {p['code']} ({p['current_uses']}/{p['max_uses'] or '∞'})",
        item_callback=lambda p: f"promo_v_{p['id']}",
        page=page,
        back_cb=None,
        nav_cb_prefix="promos-page_",
    )

    kb = InlineKeyboardBuilder()
    kb.attach(InlineKeyboardBuilder.from_markup(markup))
    kb.row(InlineKeyboardButton(text=localize("admin.promo.create"), callback_data="promo_create"))
    kb.row(InlineKeyboardButton(text=localize("btn.back"), callback_data="console"))
    markup = kb.as_markup()

    await call.message.edit_text(localize("admin.promo.title"), reply_markup=markup)
    await state.update_data(promo_paginator=paginator.get_state())


# --- View / toggle / delete promo ---

async def _show_promo_view(message, promo_id: int):
    """Shared logic: render promo detail view on a Message object."""
    from bot.database.models.main import PromoCodes
    from bot.database import Database
    from sqlalchemy import select

    async with Database().session() as s:
        promo = (await s.execute(select(PromoCodes).where(PromoCodes.id == promo_id))).scalars().first()
        if not promo:
            return

        text = localize(
            "admin.promo.detail",
            code=promo.code,
            discount_type=promo.discount_type,
            discount_value=promo.discount_value,
            current_uses=promo.current_uses,
            max_uses=promo.max_uses or "∞",
            expires_at=str(promo.expires_at or "—"),
            is_active="✅" if promo.is_active else "⛔",
        )

    toggle_text = "⛔ Деактивировать" if promo.is_active else "✅ Активировать"
    buttons = [
        (toggle_text, f"promo_toggle_{promo_id}"),
        ("🗑 Удалить", f"promo_d_{promo_id}"),
        (localize("btn.back"), "promo_mgmt"),
    ]
    await message.edit_text(text, reply_markup=simple_buttons(buttons))


@router.callback_query(F.data.startswith("promo_v_"), HasPermissionFilter(permission=Permission.PROMO_MANAGE))
async def view_promo(call: CallbackQuery, state: FSMContext):
    promo_id = int(call.data.split("_")[2])
    result = await _show_promo_view(call.message, promo_id)
    if result is None:
        from bot.database.models.main import PromoCodes
        from bot.database import Database
        from sqlalchemy import select
        async with Database().session() as s:
            promo = (await s.execute(select(PromoCodes).where(PromoCodes.id == promo_id))).scalars().first()
        if not promo:
            await call.answer(localize("promo.not_found"), show_alert=True)


@router.callback_query(F.data.startswith("promo_toggle_"), HasPermissionFilter(permission=Permission.PROMO_MANAGE))
async def toggle_promo(call: CallbackQuery, state: FSMContext):
    promo_id = int(call.data.split("_")[2])
    new_state = await toggle_promo_code(promo_id)
    if new_state is None:
        await call.answer(localize("promo.not_found"), show_alert=True)
        return

    msg = localize("admin.promo.toggled_on") if new_state else localize("admin.promo.toggled_off")
    await call.answer(msg)
    await log_audit("promo_toggle", user_id=call.from_user.id, resource_type="PromoCode", resource_id=str(promo_id))
    await _show_promo_view(call.message, promo_id)


@router.callback_query(F.data.startswith("promo_d_"), HasPermissionFilter(permission=Permission.PROMO_MANAGE))
async def confirm_delete_promo(call: CallbackQuery, state: FSMContext):
    promo_id = int(call.data.split("_")[2])
    from bot.database.models.main import PromoCodes
    from bot.database import Database
    from sqlalchemy import select

    async with Database().session() as s:
        promo = (await s.execute(select(PromoCodes).where(PromoCodes.id == promo_id))).scalars().first()
        code = promo.code if promo else "?"

    buttons = [
        (localize("btn.yes"), f"promo_dc_{promo_id}"),
        (localize("btn.no"), f"promo_v_{promo_id}"),
    ]
    await call.message.edit_text(
        localize("admin.promo.confirm_delete", code=code),
        reply_markup=simple_buttons(buttons),
    )


@router.callback_query(F.data.startswith("promo_dc_"), HasPermissionFilter(permission=Permission.PROMO_MANAGE))
async def delete_promo_confirmed(call: CallbackQuery, state: FSMContext):
    promo_id = int(call.data.split("_")[2])
    await delete_promo_code(promo_id)
    await log_audit("promo_delete", user_id=call.from_user.id, resource_type="PromoCode", resource_id=str(promo_id))
    await call.answer(localize("admin.promo.deleted"))
    await promo_management_handler(call, state)


# --- Promo creation flow ---

@router.callback_query(F.data == "promo_create", HasPermissionFilter(permission=Permission.PROMO_MANAGE))
async def promo_create_start(call: CallbackQuery, state: FSMContext):
    await call.message.edit_text(localize("admin.promo.prompt.code"), reply_markup=back("promo_mgmt"))
    await state.set_state(PromoFSM.waiting_code)


@router.message(PromoFSM.waiting_code, F.text)
async def promo_receive_code(message: Message, state: FSMContext):
    code = (message.text or "").strip().upper()[:50]
    if not code:
        await message.answer(localize("admin.promo.invalid_value"), reply_markup=back("promo_mgmt"))
        return

    existing = await get_promo_code(code)
    if existing:
        await message.answer(localize("admin.promo.code_exists"), reply_markup=back("promo_mgmt"))
        return

    await state.update_data(promo_code=code)
    buttons = [
        (localize("admin.promo.type.percent"), "promo_type_percent"),
        (localize("admin.promo.type.fixed"), "promo_type_fixed"),
        (localize("admin.promo.type.balance"), "promo_type_balance"),
        (localize("btn.back"), "promo_mgmt"),
    ]
    await message.answer(localize("admin.promo.prompt.type"), reply_markup=simple_buttons(buttons))
    await state.set_state(PromoFSM.waiting_type)


@router.callback_query(F.data.startswith("promo_type_"), PromoFSM.waiting_type)
async def promo_receive_type(call: CallbackQuery, state: FSMContext):
    dtype = call.data.split("_")[2]  # "percent", "fixed", or "balance"
    await state.update_data(promo_type=dtype)
    if dtype == "balance":
        type_label = localize("admin.promo.type.balance")
    elif dtype == "percent":
        type_label = "%"
    else:
        type_label = localize("admin.promo.type.fixed")
    await call.message.edit_text(
        localize("admin.promo.prompt.value", type=type_label),
        reply_markup=back("promo_mgmt"),
    )
    await state.set_state(PromoFSM.waiting_value)


@router.message(PromoFSM.waiting_value, F.text)
async def promo_receive_value(message: Message, state: FSMContext):
    try:
        value = float(message.text.strip())
        if value <= 0:
            raise ValueError
        data = await state.get_data()
        if data.get('promo_type') == 'percent' and value > 100:
            raise ValueError
    except (ValueError, TypeError):
        await message.answer(localize("admin.promo.invalid_value"), reply_markup=back("promo_mgmt"))
        return

    await state.update_data(promo_value=value)
    await message.answer(localize("admin.promo.prompt.max_uses"), reply_markup=back("promo_mgmt"))
    await state.set_state(PromoFSM.waiting_max_uses)


@router.message(PromoFSM.waiting_max_uses, F.text)
async def promo_receive_max_uses(message: Message, state: FSMContext):
    try:
        max_uses = int(message.text.strip())
        if max_uses < 0:
            raise ValueError
    except (ValueError, TypeError):
        await message.answer(localize("admin.promo.invalid_value"), reply_markup=back("promo_mgmt"))
        return

    await state.update_data(promo_max_uses=max_uses)
    await message.answer(localize("admin.promo.prompt.expires"), reply_markup=back("promo_mgmt"))
    await state.set_state(PromoFSM.waiting_expires)


@router.message(PromoFSM.waiting_expires, F.text)
async def promo_receive_expires(message: Message, state: FSMContext):
    text = message.text.strip()
    if text == "0":
        expires_at = None
    else:
        try:
            expires_at = datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            await message.answer(localize("admin.promo.invalid_date"), reply_markup=back("promo_mgmt"))
            return

    await state.update_data(promo_expires=expires_at.isoformat() if expires_at else None)

    data = await state.get_data()
    if data.get('promo_type') == 'balance':
        # Balance promos have no item/category binding — create immediately
        await _finalize_promo_creation(message, state, message.from_user.id)
        return

    buttons = [
        ("📂 " + localize("admin.promo.binding.category"), "promo_bind_category"),
        ("📦 " + localize("admin.promo.binding.item"), "promo_bind_item"),
        ("🚫 " + localize("admin.promo.binding.none"), "promo_bind_none"),
        (localize("btn.back"), "promo_mgmt"),
    ]
    await message.answer(localize("admin.promo.prompt.binding_type"), reply_markup=simple_buttons(buttons))
    await state.set_state(PromoFSM.waiting_binding_type)


@router.callback_query(F.data.startswith("promo_bind_"), PromoFSM.waiting_binding_type)
async def promo_binding_type_chosen(call: CallbackQuery, state: FSMContext):
    choice = call.data.replace("promo_bind_", "")  # "category", "item", or "none"

    if choice == "none":
        await _finalize_promo_creation(call.message, state, call.from_user.id)
        return

    await state.update_data(promo_binding_type=choice)
    if choice == "category":
        prompt = localize("admin.promo.prompt.category_name")
    else:
        prompt = localize("admin.promo.prompt.item_name")
    await call.message.edit_text(prompt, reply_markup=back("promo_mgmt"))
    await state.set_state(PromoFSM.waiting_binding_name)


@router.message(PromoFSM.waiting_binding_name, F.text)
async def promo_receive_binding_name(message: Message, state: FSMContext):
    data = await state.get_data()
    binding_type = data.get('promo_binding_type')
    name = (message.text or "").strip()

    if binding_type == "category":
        cat = await check_category(name)
        if not cat:
            await message.answer(localize("admin.promo.category_not_found"), reply_markup=back("promo_mgmt"))
            return
        await state.update_data(promo_category_id=cat['id'])
    else:
        item = await get_item_info(name)
        if not item:
            await message.answer(localize("admin.promo.item_not_found"), reply_markup=back("promo_mgmt"))
            return
        await state.update_data(promo_item_id=item['id'])

    await _finalize_promo_creation(message, state, message.from_user.id)


async def _finalize_promo_creation(target, state: FSMContext, user_id: int):
    """Create promo code from accumulated state data. `target` is Message (has .answer)."""
    data = await state.get_data()
    expires_at = datetime.fromisoformat(data['promo_expires']) if data.get('promo_expires') else None

    promo_id = await create_promo_code(
        code=data['promo_code'],
        discount_type=data['promo_type'],
        discount_value=data['promo_value'],
        max_uses=data.get('promo_max_uses', 0),
        expires_at=expires_at,
        category_id=data.get('promo_category_id'),
        item_id=data.get('promo_item_id'),
    )

    reply = target.answer if hasattr(target, 'answer') else target.edit_text

    if promo_id:
        await reply(
            localize("admin.promo.created", code=data['promo_code']),
            reply_markup=back("promo_mgmt"),
        )
        await log_audit(
            "promo_create",
            user_id=user_id,
            resource_type="PromoCode",
            resource_id=data['promo_code'],
        )
    else:
        await reply(localize("admin.promo.code_exists"), reply_markup=back("promo_mgmt"))

    await state.clear()
