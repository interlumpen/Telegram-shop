from sqlalchemy import exc, select, update

from bot.database.methods.read import invalidate_user_cache, invalidate_stats_cache, invalidate_item_cache, \
    invalidate_category_cache
from bot.database.methods.cache_utils import safe_create_task
from bot.database.models import User, Goods, Categories, BoughtGoods, Role
from bot.database.models.main import PromoCodes
from bot.database import Database
from bot.logger_mesh import logger


async def set_role(telegram_id: int, role: int) -> None:
    """Set user's role (by Telegram ID) and commit."""
    async with Database().session() as s:
        await s.execute(
            update(User).where(User.telegram_id == telegram_id).values(role_id=role)
        )

    safe_create_task(invalidate_user_cache(telegram_id))


async def update_balance(telegram_id: int, summ: int) -> None:
    """Increase user's balance by `summ` and commit."""
    async with Database().session() as s:
        await s.execute(
            update(User).where(User.telegram_id == telegram_id).values(balance=User.balance + summ)
        )

    safe_create_task(invalidate_user_cache(telegram_id))
    safe_create_task(invalidate_stats_cache())


async def update_item(item_name: str, new_name: str, description: str, price, category: str) -> tuple[bool, str | None]:
    """Update a Goods record with proper locking.

    Returns ``(success, error_code)``. The error code is a stable key
    ("position_invalid", "position_exists", "db_error")
    """
    try:
        async with Database().session() as s:
            result = await s.execute(
                select(Goods).where(Goods.name == item_name).with_for_update()
            )
            goods = result.scalars().one_or_none()

            if not goods:
                return False, "position_invalid"

            cat_id = (await s.execute(
                select(Categories.id).where(Categories.name == category)
            )).scalar()
            if not cat_id:
                return False, "position_invalid"

            if new_name == item_name:
                goods.description = description
                goods.price = price
                goods.category_id = cat_id
                return True, None

            existing = (await s.execute(
                select(Goods).where(Goods.name == new_name)
            )).scalars().first()
            if existing:
                return False, "position_exists"

            goods.name = new_name
            goods.description = description
            goods.price = price
            goods.category_id = cat_id

            await s.execute(
                update(BoughtGoods).where(BoughtGoods.item_name == item_name).values(item_name=new_name)
            )

            safe_create_task(invalidate_item_cache(item_name, category))
            if new_name != item_name:
                safe_create_task(invalidate_item_cache(new_name, category))

            return True, None

    except exc.SQLAlchemyError:
        # Log the real cause — this branch previously swallowed the error silently,
        # leaving a "something went wrong" with nothing in the logs to diagnose.
        logger.error("update_item(%r -> %r) failed", item_name, new_name, exc_info=True)
        return False, "db_error"


async def set_item_sale(item_name: str, sale_percent, sale_until) -> bool:
    """Set or clear a time-limited sale on a Goods item.

    Pass sale_percent/sale_until = None to disable the sale. Returns True if the
    item existed. Invalidates the item cache so the price refreshes immediately.
    """
    async with Database().session() as s:
        result = await s.execute(
            select(Goods).where(Goods.name == item_name).with_for_update()
        )
        goods = result.scalars().one_or_none()
        if not goods:
            return False
        goods.sale_percent = sale_percent
        goods.sale_until = sale_until
        safe_create_task(invalidate_item_cache(item_name))
        return True


async def set_user_blocked(telegram_id: int, blocked: bool) -> bool:
    """Set user blocked status and commit."""
    async with Database().session() as s:
        result = await s.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalars().first()
        if user:
            user.is_blocked = blocked
            safe_create_task(invalidate_user_cache(telegram_id))
            return True
        return False


async def is_user_blocked(telegram_id: int) -> bool:
    """Check if user is blocked."""
    async with Database().session() as s:
        result = await s.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalars().first()
        return user.is_blocked if user else False


async def update_category(category_name: str, new_name: str) -> None:
    """Rename a category. With integer PKs, just update the name field."""
    async with Database().session() as s:
        result = await s.execute(
            select(Categories).where(Categories.name == category_name).with_for_update()
        )
        category = result.scalars().one_or_none()

        if not category:
            raise ValueError("Category not found")

        category.name = new_name

    safe_create_task(invalidate_category_cache(category_name))
    if new_name != category_name:
        safe_create_task(invalidate_category_cache(new_name))


async def update_role(role_id: int, name: str, permissions: int) -> tuple[bool, str | None]:
    """Update role name and permissions. Returns (success, error_message)."""
    async with Database().session() as s:
        result = await s.execute(
            select(Role).where(Role.id == role_id).with_for_update()
        )
        role = result.scalars().first()
        if not role:
            return False, "Role not found"
        if role.name != name:
            existing = (await s.execute(select(Role).where(Role.name == name))).scalars().first()
            if existing:
                return False, "Role name already exists"
        role.name = name
        role.permissions = permissions
        return True, None


async def toggle_promo_code(promo_id: int) -> bool | None:
    """Toggle promo code active status. Returns new is_active or None if not found."""
    async with Database().session() as s:
        result = await s.execute(
            select(PromoCodes).where(PromoCodes.id == promo_id).with_for_update()
        )
        promo = result.scalars().first()
        if not promo:
            return None
        promo.is_active = not promo.is_active
        return promo.is_active
