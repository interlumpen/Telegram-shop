from datetime import datetime
from typing import Optional

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from bot.i18n import localize
from bot.database.models import Permission
from bot.database.methods import get_all_users
from bot.keyboards import back, close, simple_buttons
from bot.database.methods.audit import log_audit
from bot.filters import HasPermissionFilter
from bot.handlers.other import caller_name
from bot.misc import BroadcastMessage, sanitize_html
from bot.misc.services import BroadcastManager, BroadcastStats
from bot.states import BroadcastFSM

router = Router()

# Per-admin broadcast managers. Keyed by admin id so two admins don't clobber
# each other's manager, and so a re-entrant second message (the FSM stays in
# waiting_message for the whole send) can be rejected while one is in flight.
# A reserved slot holds None until the manager is constructed.
broadcast_managers: dict[int, Optional[BroadcastManager]] = {}


def _cancel_keyboard():
    """Progress-message keyboard with a working cancel button."""
    return simple_buttons([(localize("broadcast.btn.cancel"), "cancel_broadcast")])


@router.callback_query(F.data == "send_message", HasPermissionFilter(permission=Permission.BROADCAST))
async def send_message_callback_handler(call: CallbackQuery, state: FSMContext):
    """Beginning of mailing"""
    await call.message.edit_text(
        localize("broadcast.prompt"),
        reply_markup=back("console"),
    )
    await state.set_state(BroadcastFSM.waiting_message)


@router.message(BroadcastFSM.waiting_message, F.text)
async def broadcast_messages(message: Message, state: FSMContext):
    """Executing mailing with progress bar"""
    admin_id = message.from_user.id

    if admin_id in broadcast_managers:
        await message.answer(localize("broadcast.already_running"))
        return
    broadcast_managers[admin_id] = None

    try:
        # Validate broadcast message
        broadcast_msg = BroadcastMessage(
            text=message.text,
            parse_mode="HTML"
        )

        # Sanitize HTML if needed
        safe_text = sanitize_html(broadcast_msg.text) if broadcast_msg.parse_mode == "HTML" else broadcast_msg.text

        users = await get_all_users()
        user_ids = [int(row[0]) for row in users]

        await message.delete()

        # Create a progress message
        progress_msg = await message.answer(
            localize("broadcast.creating", ids=len(user_ids)),
            reply_markup=_cancel_keyboard()
        )

        # Progress update function
        async def update_progress(stats: BroadcastStats):
            progress = (stats.sent + stats.failed + stats.blocked) / stats.total * 100

            try:
                await progress_msg.edit_text(
                    localize("broadcast.progress",
                             progress=progress,
                             sent=stats.sent,
                             total=stats.total,
                             failed=stats.failed,
                             time=int((datetime.now() - stats.start_time).total_seconds())),
                    reply_markup=_cancel_keyboard()
                )
            except (TelegramBadRequest, TelegramForbiddenError) as e:
                await log_audit("broadcast_progress_fail", level="WARNING", details=str(e))

        # Start the mailing at the manager's default Telegram-safe pace.
        manager = BroadcastManager(bot=message.bot)
        broadcast_managers[admin_id] = manager

        stats = await manager.broadcast(
            user_ids=user_ids,
            text=safe_text,
            reply_markup=close(),
            parse_mode=str(broadcast_msg.parse_mode),
            progress_callback=update_progress
        )

        # Final message
        duration = int(stats.duration) if stats.duration else 0
        try:
            await progress_msg.edit_text(
                localize("broadcast.done",
                         total=stats.total,
                         sent=stats.sent,
                         failed=stats.failed,
                         blocked=stats.blocked,
                         success=f"{stats.success_rate:.1f}",
                         duration=duration),
                reply_markup=back("send_message")
            )
        except TelegramBadRequest as e:
            # "message is not modified" etc. — the broadcast itself succeeded.
            await log_audit("broadcast_final_edit_fail", level="WARNING", details=str(e))

        # Logging
        admin_name = caller_name(message)
        await log_audit("broadcast_sent", user_id=admin_id,
                        details=f"admin={admin_name}, delivered={stats.sent}/{stats.total}, duration={duration}s")

    except Exception as e:
        await message.answer(
            localize("errors.invalid_data"),
            reply_markup=back("send_message")
        )
        await log_audit("broadcast_error", level="ERROR", user_id=admin_id, details=str(e))

    finally:
        broadcast_managers.pop(admin_id, None)
        await state.clear()


@router.callback_query(F.data == "cancel_broadcast", HasPermissionFilter(permission=Permission.BROADCAST))
async def cancel_broadcast_handler(call: CallbackQuery):
    """Cancel the caller's current mailing."""
    manager = broadcast_managers.get(call.from_user.id)
    if manager is not None:
        manager.cancel()
        await call.answer(localize("broadcast.cancel"), show_alert=True)
    else:
        await call.answer(localize("broadcast.warning"), show_alert=True)
