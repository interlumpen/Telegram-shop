from bot.database.methods.read import invalidate_item_cache, invalidate_category_cache
from bot.database.methods.cache_utils import safe_create_task
from bot.database.models import Database, Goods, ItemValues, Categories
from bot.database.methods.audit import log_audit
from bot.database.main import run_sync


def _delete_item(item_name: str) -> None:
    """Delete a product and all of its stock entries."""
    with Database().session() as s:
        item = s.query(Goods).filter(Goods.name == item_name).first()
        if item:
            s.query(ItemValues).filter(ItemValues.item_id == item.id).delete(synchronize_session=False)
            s.delete(item)

    safe_create_task(invalidate_item_cache(item_name))


def _delete_only_items(item_name: str) -> None:
    """Delete all stock entries (ItemValues) for a product, keep Goods row."""
    with Database().session() as s:
        item_id = s.query(Goods.id).filter(Goods.name == item_name).scalar()
        if item_id:
            s.query(ItemValues).filter(ItemValues.item_id == item_id).delete(synchronize_session=False)


def _delete_item_from_position(item_id: int) -> None:
    """Delete a single stock row by its ItemValues id."""
    with Database().session() as s:
        s.query(ItemValues).filter(ItemValues.id == item_id).delete(synchronize_session=False)


def _delete_category(category_name: str) -> None:
    """Delete a category and all products/stock inside it (CASCADE handles items)."""
    with Database().session() as s:
        cat = s.query(Categories).filter(Categories.name == category_name).first()
        if not cat:
            return
        items = s.query(Goods.name).filter(Goods.category_id == cat.id).all()
        if items:
            item_names = [i[0] for i in items]
            log_audit(
                "cascade_delete",
                resource_type="Category",
                resource_id=category_name,
                details=f"deleted items: {item_names}",
            )
        s.delete(cat)

    # Invalidate the cache
    safe_create_task(invalidate_category_cache(category_name))


# Async public API
delete_item = run_sync(_delete_item)
delete_only_items = run_sync(_delete_only_items)
delete_item_from_position = run_sync(_delete_item_from_position)
delete_category = run_sync(_delete_category)
