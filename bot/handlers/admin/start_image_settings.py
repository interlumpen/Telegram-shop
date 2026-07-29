import hashlib

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.exc import SQLAlchemyError

from bot.database.methods import (
    check_role_cached,
    get_start_image_file_id,
    set_start_image_file_id,
)
from bot.database.models import Permission
from bot.filters import HasPermissionFilter
from bot.handlers.user.main import render_start_screen
from bot.i18n import localize
from bot.keyboards import back, simple_buttons, start_image_settings_keyboard
from bot.logger_mesh import logger
from bot.states import StorefrontSettingsFSM

router = Router()


async def _authorize_callback(call: CallbackQuery) -> int | None:
    role = await check_role_cached(call.from_user.id) or 0
    if Permission.granted(role, Permission.SETTINGS_MANAGE):
        return role
    await call.answer(localize("admin.menu.rights"), show_alert=True)
    return None


async def _authorize_message(message: Message) -> bool:
    role = await check_role_cached(message.from_user.id) or 0
    if Permission.granted(role, Permission.SETTINGS_MANAGE):
        return True
    await message.answer(localize("admin.menu.rights"))
    return False


def _settings_card_text(configured: bool, notice: str | None = None) -> str:
    status_key = (
        "admin.start_image.status_configured"
        if configured else "admin.start_image.status_empty"
    )
    card = f"{localize('admin.start_image.title')}\n\n{localize(status_key)}"
    return f"{notice}\n\n{card}" if notice else card


async def _answer_settings_card(
    message: Message,
    configured: bool,
    notice: str | None = None,
) -> None:
    await message.answer(
        _settings_card_text(configured, notice),
        reply_markup=start_image_settings_keyboard(configured),
    )


@router.callback_query(
    F.data == "start_image_settings",
    HasPermissionFilter(permission=Permission.SETTINGS_MANAGE),
)
async def start_image_settings_handler(call: CallbackQuery, state: FSMContext):
    if await _authorize_callback(call) is None:
        return
    await state.clear()
    configured = bool(await get_start_image_file_id())
    await call.message.edit_text(
        _settings_card_text(configured),
        reply_markup=start_image_settings_keyboard(configured),
    )


@router.callback_query(
    F.data == "start_image_upload",
    HasPermissionFilter(permission=Permission.SETTINGS_MANAGE),
)
async def start_image_upload_handler(call: CallbackQuery, state: FSMContext):
    if await _authorize_callback(call) is None:
        return
    await call.message.edit_text(
        localize("admin.start_image.prompt"),
        reply_markup=back("start_image_settings"),
    )
    await state.set_state(StorefrontSettingsFSM.waiting_start_image)


@router.message(
    StorefrontSettingsFSM.waiting_start_image,
    F.photo,
    HasPermissionFilter(permission=Permission.SETTINGS_MANAGE),
)
async def save_start_image_handler(message: Message, state: FSMContext):
    if not await _authorize_message(message):
        return
    file_id = message.photo[-1].file_id
    try:
        previously_configured = await set_start_image_file_id(
            file_id,
            message.from_user.id,
        )
    except (SQLAlchemyError, RuntimeError):
        logger.error("start_image_persistence_failed")
        await message.answer(
            localize("admin.start_image.save_failed"),
            reply_markup=back("start_image_settings"),
        )
        return

    await state.clear()
    notice_key = (
        "admin.start_image.replaced"
        if previously_configured else "admin.start_image.added"
    )
    await _answer_settings_card(message, True, localize(notice_key))


@router.message(
    StorefrontSettingsFSM.waiting_start_image,
    HasPermissionFilter(permission=Permission.SETTINGS_MANAGE),
)
async def reject_non_photo_handler(message: Message):
    if not await _authorize_message(message):
        return
    await message.answer(
        localize("admin.start_image.photo_required"),
        reply_markup=back("start_image_settings"),
    )


@router.callback_query(
    F.data == "start_image_remove",
    HasPermissionFilter(permission=Permission.SETTINGS_MANAGE),
)
async def start_image_remove_handler(call: CallbackQuery, state: FSMContext):
    if await _authorize_callback(call) is None:
        return
    current_file_id = await get_start_image_file_id()
    if not current_file_id:
        await state.clear()
        await call.message.edit_text(
            _settings_card_text(False, localize("admin.start_image.already_empty")),
            reply_markup=start_image_settings_keyboard(False),
        )
        return

    await state.set_state(StorefrontSettingsFSM.confirming_start_image_removal)
    await state.update_data(
        start_image_fingerprint=hashlib.sha256(current_file_id.encode()).hexdigest()
    )
    await call.message.edit_text(
        localize("admin.start_image.remove_confirm"),
        reply_markup=simple_buttons([
            (localize("btn.yes"), "start_image_remove_confirm"),
            (localize("btn.no"), "start_image_settings"),
        ]),
    )


@router.callback_query(
    StorefrontSettingsFSM.confirming_start_image_removal,
    F.data == "start_image_remove_confirm",
    HasPermissionFilter(permission=Permission.SETTINGS_MANAGE),
)
async def start_image_remove_confirm_handler(call: CallbackQuery, state: FSMContext):
    if await _authorize_callback(call) is None:
        return
    expected_fingerprint = (await state.get_data()).get("start_image_fingerprint")
    if not expected_fingerprint:
        await state.clear()
        await call.answer(localize("admin.start_image.stale"), show_alert=True)
        return

    try:
        removed = await set_start_image_file_id(
            None,
            call.from_user.id,
            expected_file_id_fingerprint=expected_fingerprint,
        )
    except (SQLAlchemyError, RuntimeError):
        logger.error("start_image_persistence_failed")
        await call.answer(localize("admin.start_image.save_failed"), show_alert=True)
        return

    await state.clear()
    if removed is None:
        configured = bool(await get_start_image_file_id())
        await call.answer(localize("admin.start_image.stale"), show_alert=True)
        await call.message.edit_text(
            _settings_card_text(configured),
            reply_markup=start_image_settings_keyboard(configured),
        )
        return

    notice_key = "admin.start_image.removed" if removed else "admin.start_image.already_empty"
    await call.message.edit_text(
        _settings_card_text(False, localize(notice_key)),
        reply_markup=start_image_settings_keyboard(False),
    )


@router.callback_query(
    F.data == "start_image_preview",
    HasPermissionFilter(permission=Permission.SETTINGS_MANAGE),
)
async def start_image_preview_handler(call: CallbackQuery):
    role = await _authorize_callback(call)
    if role is None:
        return
    await call.answer()
    await call.message.answer(localize("admin.start_image.preview_label"))
    await render_start_screen(call.message, role)
