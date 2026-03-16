from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from bot.i18n import localize
from bot.database.models import Permission
from bot.database.methods import (
    check_role_cached, check_user_cached, check_role_name_by_id,
    set_role, get_all_roles, get_role_by_id, get_roles_with_max_perms,
    count_users_with_role, create_role, update_role, delete_role,
)
from bot.keyboards import back, close, simple_buttons
from bot.database.methods.audit import log_audit
from bot.filters import HasPermissionFilter
from bot.states import RoleMgmtFSM

router = Router()

PERM_LABELS = {
    Permission.USE: "USE",
    Permission.BROADCAST: "BROADCAST",
    Permission.SETTINGS_MANAGE: "SETTINGS",
    Permission.USERS_MANAGE: "USERS",
    Permission.CATALOG_MANAGE: "CATALOG",
    Permission.ADMINS_MANAGE: "ADMINS",
    Permission.OWN: "OWNER",
    Permission.STATS_VIEW: "STATS",
    Permission.BALANCE_MANAGE: "BALANCE",
    Permission.PROMO_MANAGE: "PROMOS",
}


def _format_permissions(perms: int) -> str:
    active = [label for bit, label in PERM_LABELS.items() if perms & bit]
    return ", ".join(active) if active else "—"


def _build_perms_keyboard(current_perms: int, caller_perms: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for bit, label in PERM_LABELS.items():
        if (bit & caller_perms) != bit:
            continue
        checked = "✓" if (current_perms & bit) else "  "
        kb.button(text=f"[{checked}] {label}", callback_data=f"rp_t_{bit}")
    kb.adjust(2)
    kb.row(InlineKeyboardButton(text=localize('admin.roles.confirm'), callback_data='rp_done'))
    kb.row(InlineKeyboardButton(text=localize('btn.back'), callback_data='role_mgmt'))
    return kb.as_markup()


# Role list (entry from admin console)

@router.callback_query(F.data == 'role_mgmt', HasPermissionFilter(Permission.ADMINS_MANAGE))
async def role_management_handler(call: CallbackQuery, state: FSMContext):
    await state.clear()
    caller_perms = await check_role_cached(call.from_user.id) or 0
    roles = await get_all_roles()

    buttons = []
    for role in roles:
        if Permission.is_subset(role['permissions'], caller_perms):
            buttons.append((f"{role['name']} ({_format_permissions(role['permissions'])})", f"role_v_{role['id']}"))

    buttons.append((localize('admin.roles.create'), 'role_new'))
    buttons.append((localize('btn.back'), 'console'))

    await call.message.edit_text(
        localize('admin.roles.list_title'),
        reply_markup=simple_buttons(buttons, per_row=1)
    )


# View role detail

@router.callback_query(F.data.startswith('role_v_'), HasPermissionFilter(Permission.ADMINS_MANAGE))
async def role_view_handler(call: CallbackQuery):
    try:
        role_id = int(call.data[7:])
    except (ValueError, TypeError):
        await call.answer(localize('errors.invalid_data'), show_alert=True)
        return

    caller_perms = await check_role_cached(call.from_user.id) or 0
    role = await get_role_by_id(role_id)

    if not role or not Permission.is_subset(role['permissions'], caller_perms):
        await call.answer(localize('admin.roles.perm_denied'), show_alert=True)
        return

    user_count = await count_users_with_role(role_id)
    text = localize('admin.roles.detail',
                     name=role['name'],
                     perms=_format_permissions(role['permissions']),
                     users=user_count)

    actions = []
    actions.append((localize('admin.roles.edit'), f"role_e_{role_id}"))
    if not role['default'] and role['name'] not in ('USER', 'ADMIN', 'OWNER') and user_count == 0:
        actions.append((localize('admin.roles.delete'), f"role_d_{role_id}"))
    actions.append((localize('btn.back'), 'role_mgmt'))

    await call.message.edit_text(text, parse_mode='HTML', reply_markup=simple_buttons(actions, per_row=1))


# Create role flow

@router.callback_query(F.data == 'role_new', HasPermissionFilter(Permission.ADMINS_MANAGE))
async def role_create_start(call: CallbackQuery, state: FSMContext):
    await call.message.edit_text(
        localize('admin.roles.prompt_name'),
        reply_markup=back('role_mgmt')
    )
    await state.set_state(RoleMgmtFSM.waiting_role_name)


@router.message(RoleMgmtFSM.waiting_role_name, F.text)
async def role_create_name(message: Message, state: FSMContext):
    name = message.text.strip().upper()
    if not name or len(name) > 64:
        await message.answer(localize('admin.roles.name_invalid'), reply_markup=back('role_mgmt'))
        return

    caller_perms = await check_role_cached(message.from_user.id) or 0
    await state.update_data(role_name=name, role_perms=0, caller_perms=caller_perms, mode='create')
    await state.set_state(RoleMgmtFSM.waiting_role_perms)
    await message.answer(
        localize('admin.roles.select_perms', name=name),
        reply_markup=_build_perms_keyboard(0, caller_perms)
    )


# Edit role flow

@router.callback_query(F.data.startswith('role_e_'), HasPermissionFilter(Permission.ADMINS_MANAGE))
async def role_edit_start(call: CallbackQuery, state: FSMContext):
    try:
        role_id = int(call.data[7:])
    except (ValueError, TypeError):
        await call.answer(localize('errors.invalid_data'), show_alert=True)
        return

    caller_perms = await check_role_cached(call.from_user.id) or 0
    role = await get_role_by_id(role_id)

    if not role or not Permission.is_subset(role['permissions'], caller_perms):
        await call.answer(localize('admin.roles.perm_denied'), show_alert=True)
        return

    await state.update_data(
        role_id=role_id,
        role_name=role['name'],
        role_perms=role['permissions'],
        caller_perms=caller_perms,
        mode='edit'
    )
    await call.message.edit_text(
        localize('admin.roles.edit_name_prompt'),
        reply_markup=back(f'role_v_{role_id}')
    )
    await state.set_state(RoleMgmtFSM.editing_role_name)


@router.message(RoleMgmtFSM.editing_role_name, F.text)
async def role_edit_name(message: Message, state: FSMContext):
    data = await state.get_data()
    text = message.text.strip()

    if text == '/skip':
        name = data.get('role_name')
    else:
        name = text.upper()
        if not name or len(name) > 64:
            await message.answer(localize('admin.roles.name_invalid'),
                                 reply_markup=back(f"role_v_{data.get('role_id')}"))
            return

    caller_perms = data.get('caller_perms', 0)
    current_perms = data.get('role_perms', 0)
    await state.update_data(role_name=name)
    await state.set_state(RoleMgmtFSM.editing_role_perms)
    await message.answer(
        localize('admin.roles.select_perms', name=name),
        reply_markup=_build_perms_keyboard(current_perms, caller_perms)
    )


# Toggle permissions (shared by create & edit)

@router.callback_query(F.data.startswith('rp_t_'), RoleMgmtFSM.waiting_role_perms)
async def role_toggle_perm_create(call: CallbackQuery, state: FSMContext):
    await _toggle_perm(call, state)


@router.callback_query(F.data.startswith('rp_t_'), RoleMgmtFSM.editing_role_perms)
async def role_toggle_perm_edit(call: CallbackQuery, state: FSMContext):
    await _toggle_perm(call, state)


async def _toggle_perm(call: CallbackQuery, state: FSMContext):
    try:
        bit = int(call.data[5:])
    except (ValueError, TypeError):
        return

    data = await state.get_data()
    current = data.get('role_perms', 0)
    caller_perms = data.get('caller_perms', 0)

    if (bit & caller_perms) != bit:
        await call.answer(localize('admin.roles.perm_denied'), show_alert=True)
        return

    current ^= bit
    await state.update_data(role_perms=current)

    await call.message.edit_reply_markup(
        reply_markup=_build_perms_keyboard(current, caller_perms)
    )
    await call.answer()


# Confirm permissions (shared by create & edit)

@router.callback_query(F.data == 'rp_done', RoleMgmtFSM.waiting_role_perms)
async def role_perms_done_create(call: CallbackQuery, state: FSMContext):
    await _perms_done(call, state)


@router.callback_query(F.data == 'rp_done', RoleMgmtFSM.editing_role_perms)
async def role_perms_done_edit(call: CallbackQuery, state: FSMContext):
    await _perms_done(call, state)


async def _perms_done(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    mode = data.get('mode')
    name = data.get('role_name')
    perms = data.get('role_perms', 0)
    caller_perms = data.get('caller_perms', 0)

    if not Permission.is_subset(perms, caller_perms):
        await call.answer(localize('admin.roles.perm_denied'), show_alert=True)
        return

    await state.clear()

    if mode == 'create':
        role_id = await create_role(name, perms)
        if role_id is None:
            await call.message.edit_text(
                localize('admin.roles.name_exists'),
                reply_markup=back('role_mgmt')
            )
        else:
            await log_audit("create_role", user_id=call.from_user.id,
                      resource_type="Role", resource_id=str(role_id),
                      details=f"name={name}, perms={perms}")
            await call.message.edit_text(
                localize('admin.roles.created', name=name),
                reply_markup=back('role_mgmt')
            )
    elif mode == 'edit':
        role_id = data.get('role_id')
        success, err = await update_role(role_id, name, perms)
        if success:
            await log_audit("update_role", user_id=call.from_user.id,
                      resource_type="Role", resource_id=str(role_id),
                      details=f"name={name}, perms={perms}")
            await call.message.edit_text(
                localize('admin.roles.updated', name=name),
                reply_markup=back('role_mgmt')
            )
        else:
            await call.message.edit_text(
                localize('admin.roles.name_exists') if 'already exists' in (err or '') else str(err),
                reply_markup=back('role_mgmt')
            )


# Delete role

@router.callback_query(F.data.startswith('role_d_'), HasPermissionFilter(Permission.ADMINS_MANAGE))
async def role_delete_prompt(call: CallbackQuery):
    try:
        role_id = int(call.data[7:])
    except (ValueError, TypeError):
        await call.answer(localize('errors.invalid_data'), show_alert=True)
        return

    caller_perms = await check_role_cached(call.from_user.id) or 0
    role = await get_role_by_id(role_id)

    if not role or not Permission.is_subset(role['permissions'], caller_perms):
        await call.answer(localize('admin.roles.perm_denied'), show_alert=True)
        return

    buttons = [
        (localize('btn.yes'), f"role_dc_{role_id}"),
        (localize('btn.no'), f"role_v_{role_id}"),
    ]
    await call.message.edit_text(
        localize('admin.roles.delete_confirm', name=role['name']),
        reply_markup=simple_buttons(buttons, per_row=2)
    )


@router.callback_query(F.data.startswith('role_dc_'), HasPermissionFilter(Permission.ADMINS_MANAGE))
async def role_delete_confirm(call: CallbackQuery):
    try:
        role_id = int(call.data[8:])
    except (ValueError, TypeError):
        await call.answer(localize('errors.invalid_data'), show_alert=True)
        return

    caller_perms = await check_role_cached(call.from_user.id) or 0
    role = await get_role_by_id(role_id)

    if not role or not Permission.is_subset(role['permissions'], caller_perms):
        await call.answer(localize('admin.roles.perm_denied'), show_alert=True)
        return

    success, err = await delete_role(role_id)
    if success:
        await log_audit("delete_role", user_id=call.from_user.id,
                  resource_type="Role", resource_id=str(role_id),
                  details=f"name={role['name']}")
        await call.message.edit_text(
            localize('admin.roles.deleted'),
            reply_markup=back('role_mgmt')
        )
    else:
        await call.message.edit_text(
            localize('admin.roles.delete_fail', error=err),
            reply_markup=back('role_mgmt')
        )


# ── Assign role to user (from user profile) ──

@router.callback_query(F.data.startswith('asr_list_'), HasPermissionFilter(Permission.ADMINS_MANAGE))
async def assign_role_list(call: CallbackQuery):
    try:
        target_id = int(call.data[9:])
    except (ValueError, TypeError):
        await call.answer(localize('errors.invalid_data'), show_alert=True)
        return

    caller_perms = await check_role_cached(call.from_user.id) or 0

    db_user = await check_user_cached(target_id)
    if not db_user:
        await call.answer(localize('admin.users.not_found'), show_alert=True)
        return

    target_role_name = await check_role_name_by_id(db_user.get('role_id'))
    if target_role_name == 'OWNER':
        await call.answer(localize('admin.users.cannot_change_owner'), show_alert=True)
        return

    roles = await get_roles_with_max_perms(caller_perms)
    buttons = []
    for role in roles:
        current = " ✦" if role['id'] == db_user.get('role_id') else ""
        buttons.append((f"{role['name']}{current}", f"asr_{role['id']}_{target_id}"))
    buttons.append((localize('btn.back'), f"check-user_{target_id}"))

    await call.message.edit_text(
        localize('admin.roles.assign_prompt', id=target_id),
        reply_markup=simple_buttons(buttons, per_row=1)
    )


@router.callback_query(F.data.regexp(r'^asr_(\d+)_(\d+)$'), HasPermissionFilter(Permission.ADMINS_MANAGE))
async def assign_role_confirm(call: CallbackQuery):
    parts = call.data.split('_')
    try:
        role_id = int(parts[1])
        target_id = int(parts[2])
    except (ValueError, IndexError):
        await call.answer(localize('errors.invalid_data'), show_alert=True)
        return

    caller_perms = await check_role_cached(call.from_user.id) or 0
    role = await get_role_by_id(role_id)

    if not role or not Permission.is_subset(role['permissions'], caller_perms):
        await call.answer(localize('admin.roles.perm_denied'), show_alert=True)
        return

    db_user = await check_user_cached(target_id)
    if not db_user:
        await call.answer(localize('admin.users.not_found'), show_alert=True)
        return

    target_role_name = await check_role_name_by_id(db_user.get('role_id'))
    if target_role_name == 'OWNER':
        await call.answer(localize('admin.users.cannot_change_owner'), show_alert=True)
        return

    await set_role(target_id, role_id)

    # Invalidate middleware admin cache so new permissions take effect immediately
    from bot.main import auth_middleware
    if auth_middleware:
        auth_middleware.invalidate_admin_cache(target_id)

    user_info = await call.message.bot.get_chat(target_id)
    await call.message.edit_text(
        localize('admin.roles.assigned', name=user_info.first_name, role=role['name']),
        reply_markup=back(f'check-user_{target_id}')
    )

    try:
        await call.message.bot.send_message(
            chat_id=target_id,
            text=localize('admin.roles.assigned_notify', role=role['name']),
            reply_markup=close()
        )
    except (TelegramBadRequest, TelegramForbiddenError) as e:
        await log_audit("assign_role_notify_fail", level="ERROR", user_id=target_id, details=str(e))

    admin_info = await call.message.bot.get_chat(call.from_user.id)
    await log_audit("assign_role", user_id=call.from_user.id,
              resource_type="User", resource_id=str(target_id),
              details=f"admin={admin_info.first_name}, role={role['name']}")
