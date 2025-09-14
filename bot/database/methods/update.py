from sqlalchemy import exc

from bot.database.methods import invalidate_user_cache, invalidate_stats_cache, invalidate_item_cache, \
    invalidate_category_cache
from bot.database.methods.cache_utils import safe_create_task
from bot.database.models import User, ItemValues, Goods, Categories, BoughtGoods
from bot.database import Database
from bot.i18n import localize


def set_role(telegram_id: int, role: int) -> None:
    """Set user's role (by Telegram ID) and commit."""
    with Database().session() as s:
        s.query(User).filter(User.telegram_id == telegram_id).update(
            {User.role_id: role}
        )

    # Invalidate the user cache
    safe_create_task(invalidate_user_cache(telegram_id))


def update_balance(telegram_id: int | str, summ: int) -> None:
    """Increase user's balance by `summ` and commit."""
    with Database().session() as s:
        s.query(User).filter(User.telegram_id == telegram_id).update(
            {User.balance: User.balance + summ}
        )

    # Invalidate the cache
    safe_create_task(invalidate_user_cache(int(telegram_id)))
    safe_create_task(invalidate_stats_cache())


def update_item(item_name: str, new_name: str, description: str, price, category: str) -> tuple[bool, str | None]:
    """
    Update a Goods record with proper locking.
    """
    try:
        with Database().session() as session:
            # Blocking goods for updating
            goods = session.query(Goods).filter(
                Goods.name == item_name
            ).with_for_update().one_or_none()

            if not goods:
                return False, localize("admin.goods.update.position.invalid")

            if new_name == item_name:
                goods.description = description
                goods.price = price
                goods.category_name = category
                return True, None

            # Check that the new name is not already taken
            if session.query(Goods).filter(Goods.name == new_name).first():
                return False, localize("admin.goods.update.position.exists")

            # Create a new product
            new_goods = Goods(name=new_name, price=price, description=description, category_name=category)
            session.add(new_goods)
            session.flush()

            # Update linked records
            session.query(ItemValues).filter(ItemValues.item_name == item_name) \
                .update({ItemValues.item_name: new_name}, synchronize_session=False)

            session.query(BoughtGoods).filter(BoughtGoods.item_name == item_name) \
                .update({BoughtGoods.item_name: new_name}, synchronize_session=False)

            # Remove the old merchandise
            session.query(Goods).filter(Goods.name == item_name).delete(synchronize_session=False)

            safe_create_task(invalidate_item_cache(item_name))
            if new_name != item_name:
                safe_create_task(invalidate_item_cache(new_name))

            return True, None

    except exc.SQLAlchemyError as e:
        return False, f"DB Error: {e.__class__.__name__}"


def update_category(category_name: str, new_name: str) -> None:
    """Rename a category with proper transaction handling."""
    with Database().session() as s:
        try:
            s.begin()

            # Block the category
            category = s.query(Categories).filter(
                Categories.name == category_name
            ).with_for_update().one_or_none()

            if not category:
                s.rollback()
                raise ValueError("Category not found")

            # Updating the merchandise
            s.query(Goods).filter(Goods.category_name == category_name).update(
                {Goods.category_name: new_name}
            )

            # Update the category
            category.name = new_name

            s.commit()

            safe_create_task(invalidate_category_cache(category_name))
            if new_name != category_name:
                safe_create_task(invalidate_category_cache(new_name))

        except Exception:
            s.rollback()
            raise
