from sqlalchemy import exc

from bot.database.methods.read import invalidate_user_cache, invalidate_stats_cache, invalidate_item_cache, \
    invalidate_category_cache
from bot.database.methods.cache_utils import safe_create_task
from bot.database.models import User, ItemValues, Goods, Categories, BoughtGoods
from bot.database import Database
from bot.database.main import run_sync
from bot.i18n import localize


def _set_role(telegram_id: int, role: int) -> None:
    """Set user's role (by Telegram ID) and commit."""
    with Database().session() as s:
        s.query(User).filter(User.telegram_id == telegram_id).update(
            {User.role_id: role}
        )

    # Invalidate the user cache
    safe_create_task(invalidate_user_cache(telegram_id))


def _update_balance(telegram_id: int | str, summ: int) -> None:
    """Increase user's balance by `summ` and commit."""
    with Database().session() as s:
        s.query(User).filter(User.telegram_id == telegram_id).update(
            {User.balance: User.balance + summ}
        )

    # Invalidate the cache
    safe_create_task(invalidate_user_cache(int(telegram_id)))
    safe_create_task(invalidate_stats_cache())


def _update_item(item_name: str, new_name: str, description: str, price, category: str) -> tuple[bool, str | None]:
    """
    Update a Goods record with proper locking. Now uses integer PKs.
    """
    try:
        with Database().session() as session:
            goods = session.query(Goods).filter(
                Goods.name == item_name
            ).with_for_update().one_or_none()

            if not goods:
                return False, localize("admin.goods.update.position.invalid")

            # Resolve category_id
            cat_id = session.query(Categories.id).filter(Categories.name == category).scalar()
            if not cat_id:
                return False, localize("admin.goods.update.position.invalid")

            if new_name == item_name:
                goods.description = description
                goods.price = price
                goods.category_id = cat_id
                return True, None

            # Check that the new name is not already taken
            if session.query(Goods).filter(Goods.name == new_name).first():
                return False, localize("admin.goods.update.position.exists")

            # Simply rename in place
            goods.name = new_name
            goods.description = description
            goods.price = price
            goods.category_id = cat_id

            # Update denormalized item_name in BoughtGoods for history
            session.query(BoughtGoods).filter(BoughtGoods.item_name == item_name) \
                .update({BoughtGoods.item_name: new_name}, synchronize_session=False)

            safe_create_task(invalidate_item_cache(item_name, category))
            if new_name != item_name:
                safe_create_task(invalidate_item_cache(new_name, category))

            return True, None

    except exc.SQLAlchemyError as e:
        return False, f"DB Error: {e.__class__.__name__}"


def _set_user_blocked(telegram_id: int, blocked: bool) -> bool:
    """Set user blocked status and commit."""
    with Database().session() as s:
        user = s.query(User).filter(User.telegram_id == telegram_id).first()
        if user:
            user.is_blocked = blocked
            safe_create_task(invalidate_user_cache(telegram_id))
            return True
        return False


def _is_user_blocked(telegram_id: int) -> bool:
    """Check if user is blocked."""
    with Database().session() as s:
        user = s.query(User).filter(User.telegram_id == telegram_id).first()
        return user.is_blocked if user else False


def _update_category(category_name: str, new_name: str) -> None:
    """Rename a category. With integer PKs, just update the name field."""
    with Database().session() as s:
        category = s.query(Categories).filter(
            Categories.name == category_name
        ).with_for_update().one_or_none()

        if not category:
            raise ValueError("Category not found")

        category.name = new_name

    safe_create_task(invalidate_category_cache(category_name))
    if new_name != category_name:
        safe_create_task(invalidate_category_cache(new_name))


# Async public API
set_role = run_sync(_set_role)
update_balance = run_sync(_update_balance)
update_item = run_sync(_update_item)
set_user_blocked = run_sync(_set_user_blocked)
is_user_blocked = run_sync(_is_user_blocked)
update_category = run_sync(_update_category)
