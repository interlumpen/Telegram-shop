from sqlalchemy import func, select, delete as sa_delete

from bot.database.methods.read import invalidate_item_cache, invalidate_category_cache
from bot.database.methods.cache_utils import safe_create_task
from bot.database.models import Database, Goods, ItemValues, Categories, Role, User
from bot.database.models.main import PromoCodes, CartItems, Reviews
from bot.database.methods.audit import log_audit


async def delete_item(item_name: str) -> None:
    """Delete a product and all of its stock entries."""
    async with Database().session() as s:
        result = await s.execute(select(Goods).where(Goods.name == item_name))
        item = result.scalars().first()
        if item:
            await s.execute(sa_delete(ItemValues).where(ItemValues.item_id == item.id))
            await s.delete(item)

    safe_create_task(invalidate_item_cache(item_name))


async def delete_only_items(item_name: str) -> None:
    """Delete all stock entries (ItemValues) for a product, keep Goods row."""
    async with Database().session() as s:
        item_id = (await s.execute(select(Goods.id).where(Goods.name == item_name))).scalar()
        if item_id:
            await s.execute(sa_delete(ItemValues).where(ItemValues.item_id == item_id))


async def delete_item_from_position(item_id: int) -> None:
    """Delete a single stock row by its ItemValues id."""
    async with Database().session() as s:
        await s.execute(sa_delete(ItemValues).where(ItemValues.id == item_id))


async def delete_category(category_name: str) -> None:
    """Delete a category and all products/stock inside it (CASCADE handles items)."""
    async with Database().session() as s:
        result = await s.execute(select(Categories).where(Categories.name == category_name))
        cat = result.scalars().first()
        if not cat:
            return
        items_result = await s.execute(select(Goods.name).where(Goods.category_id == cat.id))
        items = items_result.all()
        if items:
            item_names = [i[0] for i in items]
            await log_audit(
                "cascade_delete",
                resource_type="Category",
                resource_id=category_name,
                details=f"deleted items: {item_names}",
            )
        await s.delete(cat)

    safe_create_task(invalidate_category_cache(category_name))


async def delete_role(role_id: int) -> tuple[bool, str | None]:
    """Delete a role. Fails if users are assigned, it's default, or it's a built-in role."""
    async with Database().session() as s:
        result = await s.execute(select(Role).where(Role.id == role_id))
        role = result.scalars().first()
        if not role:
            return False, "Role not found"
        if role.default:
            return False, "Cannot delete the default role"
        if role.name in ('USER', 'ADMIN', 'OWNER'):
            return False, "Cannot delete built-in roles"
        user_count = (await s.execute(
            select(func.count(User.telegram_id)).where(User.role_id == role_id)
        )).scalar() or 0
        if user_count > 0:
            return False, f"Role has {user_count} users assigned"
        await s.delete(role)
        return True, None


async def delete_promo_code(promo_id: int) -> bool:
    """Delete a promo code by ID."""
    async with Database().session() as s:
        result = await s.execute(select(PromoCodes).where(PromoCodes.id == promo_id))
        promo = result.scalars().first()
        if promo:
            await s.delete(promo)
            return True
        return False


async def remove_from_cart(cart_item_id: int, user_id: int = None) -> bool:
    """Remove a single item from cart by CartItems ID."""
    async with Database().session() as s:
        clause = CartItems.id == cart_item_id
        if user_id is not None:
            clause = clause & (CartItems.user_id == user_id)
        result = await s.execute(sa_delete(CartItems).where(clause))
        return result.rowcount > 0


async def clear_cart(user_id: int) -> int:
    """Clear all cart items for a user. Returns count deleted."""
    async with Database().session() as s:
        result = await s.execute(sa_delete(CartItems).where(CartItems.user_id == user_id))
        return result.rowcount



async def delete_review(review_id: int) -> bool:
    """Delete a review by ID."""
    async with Database().session() as s:
        result = await s.execute(sa_delete(Reviews).where(Reviews.id == review_id))
        return result.rowcount > 0
