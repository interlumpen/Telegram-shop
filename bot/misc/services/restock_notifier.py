from html import escape as html_escape

from aiogram import Bot

from bot.database.methods.delete import pop_stock_subscribers
from bot.i18n import localize
from bot.keyboards.inline import close
from bot.logger_mesh import logger
from bot.misc.services.broadcast_system import BroadcastManager


async def notify_restock(bot: Bot, item_name: str) -> int:
    """Tell everyone waiting on `item_name` that it is back, and unsubscribe them.

    Returns the number of messages actually delivered.
    """
    user_ids = await pop_stock_subscribers(item_name)
    if not user_ids:
        return 0

    manager = BroadcastManager(bot)
    stats = await manager.broadcast(
        user_ids=user_ids,
        text=localize("stock.back_in_stock", name=html_escape(item_name, quote=False)),
        reply_markup=close(),
        parse_mode="HTML",
    )

    logger.info(
        "restock notify %r: subscribers=%s sent=%s failed=%s",
        item_name, len(user_ids), stats.sent, stats.failed,
    )
    return stats.sent
