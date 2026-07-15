from sqlalchemy import exc, select, update

from bot.database.methods.read import invalidate_user_cache, invalidate_stats_cache, invalidate_item_cache, \
    invalidate_category_cache
from bot.database.methods.cache_utils import safe_create_task
from bot.database.methods.create import CART_MAX_QTY_PER_ITEM
from bot.database.models import User, Goods, Categories, BoughtGoods, Role
from bot.database.models.main import PromoCodes, CartItems
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
    # Names whose cache entries the commit invalidates. Collected inside the transaction, acted on only once it has succeeded.
    to_invalidate: list[str] = []

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
                to_invalidate = [item_name]
            else:
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
                to_invalidate = [item_name, new_name]

    except exc.SQLAlchemyError:
        logger.error("update_item(%r -> %r) failed", item_name, new_name, exc_info=True)
        return False, "db_error"

    for name in to_invalidate:
        safe_create_task(invalidate_item_cache(name, category))

    return True, None


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
        if not user:
            return False
        user.is_blocked = blocked

    safe_create_task(invalidate_user_cache(telegram_id))
    return True


async def set_cart_item_quantity(cart_item_id: int, user_id: int, delta: int) -> tuple[bool, str, int]:
    """Apply `delta` to a cart line's quantity.

    Dropping to zero or below removes the line — that is what "−" on a line of
    one means. Scoped by user_id so one user cannot touch another's cart.

    Returns (success, code, new_quantity); new_quantity is 0 when the line was
    removed.
    """
    async with Database().session() as s:
        row = (await s.execute(
            select(CartItems)
            .where(CartItems.id == cart_item_id, CartItems.user_id == user_id)
            .with_for_update()
        )).scalars().first()

        if not row:
            return False, "item_not_found", 0

        new_qty = row.quantity + delta

        if new_qty <= 0:
            await s.delete(row)
            return True, "removed", 0

        if new_qty > CART_MAX_QTY_PER_ITEM:
            return False, "cart_qty_max", row.quantity

        row.quantity = new_qty
        return True, "success", new_qty


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
