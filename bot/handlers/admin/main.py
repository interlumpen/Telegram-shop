from aiogram import Router, F
from aiogram.types import CallbackQuery

from bot.i18n import localize
from bot.keyboards import admin_console_keyboard
from bot.database.methods import check_role_cached
from bot.filters import HasPermissionFilter
from bot.database.models import Permission

router = Router()


@router.callback_query(F.data == 'console', HasPermissionFilter(permission=Permission.SHOP_MANAGE))
async def console_callback_handler(call: CallbackQuery):
    """
    Admin menu (only for admins and above).
    """
    user_id = call.from_user.id
    role = await check_role_cached(user_id)
    if role > 1:
        await call.message.edit_text(localize("admin.menu.main"), reply_markup=admin_console_keyboard())
    else:
        await call.answer(localize("admin.menu.rights"))
