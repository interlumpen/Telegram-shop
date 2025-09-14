import asyncio

from bot.database.methods import invalidate_item_cache, invalidate_category_cache
from bot.database.methods.cache_utils import safe_create_task
from bot.database.models import Database, Goods, ItemValues, Categories


def delete_item(item_name: str) -> None:
    """Delete a product and all of its stock entries."""
    with Database().session() as s:
        s.query(Goods).filter(Goods.name == item_name).delete(synchronize_session=False)

    # Invalidate the cache
    safe_create_task(invalidate_item_cache(item_name))


def delete_only_items(item_name: str) -> None:
    """Delete all stock entries (ItemValues) for a product, keep Goods row."""
    with Database().session() as s:
        s.query(ItemValues).filter(ItemValues.item_name == item_name).delete(synchronize_session=False)


def delete_item_from_position(item_id: int) -> None:
    """Delete a single stock row by its ItemValues id."""
    with Database().session() as s:
        s.query(ItemValues).filter(ItemValues.id == item_id).delete(synchronize_session=False)


def delete_category(category_name: str) -> None:
    """Delete a category and all products/stock inside it."""
    with Database().session() as s:
        s.query(Categories).filter(Categories.name == category_name).delete(synchronize_session=False)

    # Invalidate the cache
    safe_create_task(invalidate_category_cache(category_name))