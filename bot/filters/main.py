from dataclasses import dataclass

from aiogram.filters import BaseFilter
from aiogram.types import Message, CallbackQuery

from bot.database.methods import check_role_cached
from bot.misc import EnvKeys


@dataclass
class ValidAmountFilter(BaseFilter):
    """
    Validation of the replenishment amount (used in FSM steps).
    """
    min_amount: int = EnvKeys.MIN_AMOUNT
    max_amount: int = EnvKeys.MAX_AMOUNT

    async def __call__(self, message: Message) -> bool:
        text: str = message.text or ""
        if not text.isdigit():
            return False
        value = int(text)
        return self.min_amount <= value <= self.max_amount


@dataclass
class HasPermissionFilter(BaseFilter):
    """
    Filter for the presence of a certain permission for the user (bit mask).
    """
    permission: int

    async def __call__(self, event: Message | CallbackQuery) -> bool:
        user_id = event.from_user.id
        # check_role_cached(user_id) returns int (bitmask of rights) or None
        user_permissions: int = await check_role_cached(user_id) or 0
        return (user_permissions & self.permission) == self.permission
