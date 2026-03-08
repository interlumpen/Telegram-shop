import hashlib
import re
from urllib.parse import urlparse

from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.enums import ChatMemberStatus

from bot.misc import EnvKeys
from bot.logger_mesh import logger

router = Router()


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
    me = await bot.get_me()
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


def is_safe_item_name(name: str) -> bool:
    """Check that the product name is safe for display"""
    # Length check
    if len(name) > 100 or len(name) < 1:
        return False

    # Block control characters (0x00-0x1F, 0x7F) but allow all printable Unicode
    if re.search(r'[\x00-\x1f\x7f]', name):
        return False

    return True
