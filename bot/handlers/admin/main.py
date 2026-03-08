from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from bot.i18n import localize
from bot.keyboards import admin_console_keyboard
from bot.database.methods import check_role_cached
from bot.filters import HasPermissionFilter
from bot.database.models import Permission
from bot.database.methods.audit import log_audit

router = Router()


def _get_auth_middleware():
    from bot.main import auth_middleware
    return auth_middleware


@router.callback_query(F.data == 'console')
async def console_callback_handler(call: CallbackQuery, state: FSMContext):
    """
    Admin menu (only for admins and above).
    """
    user_id = call.from_user.id
    role = await check_role_cached(user_id)
    if Permission.has_any_admin_perm(role):
        mw = _get_auth_middleware()
        maintenance = mw.maintenance_mode if mw else False
        await call.message.edit_text(
            localize("admin.menu.main"),
            reply_markup=admin_console_keyboard(maintenance_mode=maintenance, role=role),
        )
    else:
        await call.answer(localize("admin.menu.rights"))

    await state.clear()


@router.callback_query(F.data == 'toggle_maintenance', HasPermissionFilter(permission=Permission.SETTINGS_MANAGE))
async def toggle_maintenance_handler(call: CallbackQuery):
    """
    Toggle maintenance mode on/off.
    """
    mw = _get_auth_middleware()
    if not mw:
        return

    mw.maintenance_mode = not mw.maintenance_mode
    state_str = "ON" if mw.maintenance_mode else "OFF"
    await log_audit(
        "toggle_maintenance",
        user_id=call.from_user.id,
        details=f"admin={call.from_user.username}, state={state_str}",
    )

    if mw.maintenance_mode:
        await call.answer(localize("admin.maintenance.enabled"), show_alert=True)
    else:
        await call.answer(localize("admin.maintenance.disabled"), show_alert=True)

    role = await check_role_cached(call.from_user.id)
    await call.message.edit_text(
        localize("admin.menu.main"),
        reply_markup=admin_console_keyboard(maintenance_mode=mw.maintenance_mode, role=role),
    )
