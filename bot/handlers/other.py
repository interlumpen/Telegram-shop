import hashlib
import re
from urllib.parse import urlparse

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.enums import ChatMemberStatus

from bot.misc import EnvKeys
from bot.logger_mesh import logger

router = Router()

_EXPECTED_DELETE_FAILURES = (
    "message can't be deleted",
    "message to delete not found",
    "not enough rights to delete",
)


def _is_expected_delete_failure(error: Exception) -> bool:
    description = (getattr(error, "message", "") or str(error)).lower()
    return any(marker in description for marker in _EXPECTED_DELETE_FAILURES)


async def delete_for_text_transition(message: Message) -> None:
    """Delete an obsolete media message before sending a text destination.

    Telegram can legitimately refuse deletion for old/already-removed messages
    or missing delete rights. Those cases may fall back to sending the new
    screen alongside the old one; unrelated API errors must still propagate.
    """
    try:
        await message.delete()
    except (TelegramBadRequest, TelegramForbiddenError) as error:
        if not _is_expected_delete_failure(error):
            raise


async def transition_to_text(message: Message, text: str, **kwargs) -> None:
    """Edit a text message in place, or replace a media message with text."""
    if getattr(message, "text", None) is not None:
        await message.edit_text(text, **kwargs)
        return

    await delete_for_text_transition(message)
    await message.answer(text, **kwargs)


# Close message
@router.callback_query(F.data == 'close')
async def close_callback_handler(call: CallbackQuery):
    """processing of message closure (deletion)"""
    try:
        await call.message.delete()
    except (TelegramBadRequest, TelegramForbiddenError) as e:
        logger.warning(f"Failed to delete message: {e}")


@router.callback_query(F.data == 'dummy_button')
async def dummy_button(call: CallbackQuery):
    """“Empty” (dummy) button"""
    await call.answer("")


async def check_sub_channel(chat_member) -> bool:
    """channel subscription check"""
    return chat_member.status not in (ChatMemberStatus.LEFT, ChatMemberStatus.KICKED)


async def get_bot_info(event) -> str:
    """Bot information (name)"""
    bot = event.bot
    me = await bot.me()
    return me.username


def _any_payment_method_enabled() -> bool:
    """Is there at least one enabled payment method?"""
    cryptopay_ok = bool(EnvKeys.CRYPTO_PAY_TOKEN)
    tg_stars_ok = bool(EnvKeys.STARS_PER_VALUE)
    tg_pay_ok = bool(EnvKeys.TELEGRAM_PROVIDER_TOKEN)
    return cryptopay_ok or tg_stars_ok or tg_pay_ok


def _parse_channel_username() -> str | None:
    """Extract channel username from CHANNEL_URL env variable."""
    channel_url = EnvKeys.CHANNEL_URL or ""
    parsed = urlparse(channel_url)
    return (
        parsed.path.lstrip('/')
        if parsed.path
        else channel_url.replace("https://t.me/", "").replace("t.me/", "").lstrip('@')
    ) or None



def generate_short_hash(text: str, length: int = 8) -> str:
    """Generate a short hash for long strings to fit in callback_data"""
    return hashlib.md5(text.encode()).hexdigest()[:length]


async def display_name(bot, user_id: int) -> str:
    """A display name for *someone else*, falling back to their id."""
    try:
        chat = await bot.get_chat(user_id)
    except (TelegramBadRequest, TelegramForbiddenError) as e:
        logger.debug(f"get_chat({user_id}) failed: {e}")
        return str(user_id)
    return chat.first_name or str(user_id)


def caller_name(event) -> str:
    """The sender's display name, taken straight from the update."""
    user = getattr(event, "from_user", None)
    if user is None:
        return "unknown"
    return user.first_name or str(user.id)


def is_safe_item_name(name: str) -> bool:
    """Check that the product name is safe for display"""
    # Length check
    if len(name) > 100 or len(name) < 1:
        return False

    # Block control characters (0x00-0x1F, 0x7F) but allow all printable Unicode
    if re.search(r'[\x00-\x1f\x7f]', name):
        return False

    return True
