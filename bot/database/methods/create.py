from datetime import datetime
from decimal import Decimal

from sqlalchemy import select, exists, func as sa_func, insert as sa_insert
from sqlalchemy.exc import IntegrityError

from bot.database.models import User, ItemValues, Goods, Categories, Payments, Role
from bot.database.models.main import PromoCodes, CartItems, Reviews, StockSubscriptions, promo_scope_for
from bot.database import Database
from bot.database.methods.cache_utils import safe_create_task
from bot.database.methods.read import invalidate_stats_cache, invalidate_item_cache, invalidate_category_cache

# Cart limits: distinct positions per cart, and units of any one position.
CART_MAX_ITEMS = 10
CART_MAX_QTY_PER_ITEM = 99


async def create_user(telegram_id: int, registration_date: datetime, referral_id: int | None, role: int = 1) -> None:
    """Create user if missing; commit."""
    async with Database().session() as s:
        result = await s.execute(select(exists().where(User.telegram_id == telegram_id)))
        if result.scalar():
            return
        s.add(
            User(
                telegram_id=telegram_id,
                role_id=role,
                registration_date=registration_date,
                referral_id=referral_id,
            )
        )
        try:
            await s.flush()
        except IntegrityError:
            # Lost the race — the user now exists, which is the desired outcome.
            await s.rollback()


async def create_item(item_name: str, item_description: str, item_price: int, category_name: str) -> None:
    """Insert item (goods); commit. Resolves category_name to category_id."""
    async with Database().session() as s:
        result = await s.execute(select(exists().where(Goods.name == item_name)))
        if result.scalar():
            return
        cat = (await s.execute(select(Categories.id).where(Categories.name == category_name))).scalar()
        if not cat:
            return
        s.add(
            Goods(
                name=item_name,
                description=item_description,
                price=item_price,
                category_id=cat,
            )
        )

    safe_create_task(invalidate_stats_cache())
    # The category's cached item count changed.
    safe_create_task(invalidate_category_cache(category_name))


async def add_values_to_item(item_name: str, value: str, is_infinity: bool) -> bool:
    """Add item value if not duplicate; True if inserted. Resolves item_name to item_id."""
    value_norm = (value or "").strip()
    if not value_norm:
        return False

    try:
        async with Database().session() as s:
            item_id = (await s.execute(select(Goods.id).where(Goods.name == item_name))).scalar()
            if not item_id:
                return False

            dup = (await s.execute(
                select(exists().where(
                    ItemValues.item_id == item_id,
                    ItemValues.value == value_norm,
                ))
            )).scalar()
            if dup:
                return False

            s.add(ItemValues(item_id=item_id, value=value_norm, is_infinity=bool(is_infinity)))
    except IntegrityError:
        return False

    # Invalidate only after the commit succeeded.
    safe_create_task(invalidate_item_cache(item_name))
    return True


def normalize_values(values: list[str]) -> tuple[list[str], int, int]:
    """Trim, drop blanks and de-duplicate a batch of stock values.

    Returns ``(normalized, skipped_batch_dup, skipped_invalid)``. Shared by the
    bulk insert and replace_item_stock_and_meta so the two cannot drift.
    """
    seen: set[str] = set()
    normalized: list[str] = []
    skipped_dup = 0
    skipped_invalid = 0
    for v in values:
        v_norm = (v or "").strip()
        if not v_norm:
            skipped_invalid += 1
        elif v_norm in seen:
            skipped_dup += 1
        else:
            seen.add(v_norm)
            normalized.append(v_norm)
    return normalized, skipped_dup, skipped_invalid


async def add_values_bulk(
        item_name: str, values: list[str], is_infinity: bool = False
) -> tuple[int, int, int, int]:
    """Add a whole batch of stock values in one transaction.

    Returns ``(added, skipped_db_dup, skipped_batch_dup, skipped_invalid)``.

    ``is_infinity`` keeps the semantics of the single-value path: an infinite
    position holds exactly one row that is never consumed, so only the first
    value counts.
    """
    normalized, skipped_batch_dup, skipped_invalid = normalize_values(values)
    if is_infinity:
        normalized = normalized[:1]
    if not normalized:
        return 0, 0, skipped_batch_dup, skipped_invalid

    try:
        async with Database().session() as s:
            item_id = (await s.execute(
                select(Goods.id).where(Goods.name == item_name)
            )).scalar()
            if not item_id:
                return 0, 0, skipped_batch_dup, skipped_invalid

            existing = set((await s.execute(
                select(ItemValues.value).where(
                    ItemValues.item_id == item_id,
                    ItemValues.value.in_(normalized),
                )
            )).scalars().all())

            to_insert = [v for v in normalized if v not in existing]
            if to_insert:
                # Core insert with a list of parameter sets: one executemany
                await s.execute(
                    sa_insert(ItemValues),
                    [
                        {"item_id": item_id, "value": v, "is_infinity": bool(is_infinity)}
                        for v in to_insert
                    ],
                )

            added = len(to_insert)
            skipped_db_dup = len(normalized) - added
    except IntegrityError:
        # Lost the uq_item_value_per_item race against a concurrent upload: the
        # batch rolled back as a whole, so fall back to inserting one at a time
        # (idempotent) rather than reporting a failure for values that are fine.
        added = 0
        skipped_db_dup = 0
        for v in normalized:
            if await add_values_to_item(item_name, v, is_infinity):
                added += 1
            else:
                skipped_db_dup += 1
        return added, skipped_db_dup, skipped_batch_dup, skipped_invalid

    if added:
        safe_create_task(invalidate_item_cache(item_name))
    return added, skipped_db_dup, skipped_batch_dup, skipped_invalid


async def create_category(category_name: str) -> None:
    """Insert category; commit."""
    async with Database().session() as s:
        result = await s.execute(select(exists().where(Categories.name == category_name)))
        if result.scalar():
            return
        s.add(Categories(name=category_name))

    safe_create_task(invalidate_stats_cache())
    # Drops the cached categories:count
    safe_create_task(invalidate_category_cache(category_name))


async def create_pending_payment(provider: str, external_id: str, user_id: int, amount: int, currency: str) -> None:
    """Create pending payment."""
    async with Database().session() as s:
        s.add(Payments(
            provider=provider,
            external_id=external_id,
            user_id=user_id,
            amount=Decimal(amount),
            currency=currency,
            status="pending"
        ))


async def create_role(name: str, permissions: int) -> int | None:
    """Create a new role. Returns the new role ID, or None if name conflict."""
    async with Database().session() as s:
        result = await s.execute(select(exists().where(Role.name == name)))
        if result.scalar():
            return None
        role = Role(name=name, permissions=permissions)
        s.add(role)
        await s.flush()
        return role.id


async def create_promo_code(
        code: str,
        discount_type: str,
        discount_value,
        max_uses: int = 0,
        expires_at=None,
        category_id: int = None,
        item_id: int = None,
) -> int | None:
    """Create a promo code. Returns ID or None if code already exists.

    Raises ValueError if bound to both a category and an item.
    """
    from decimal import Decimal

    if category_id is not None and item_id is not None:
        raise ValueError("a promo code cannot be bound to both a category and an item")

    async with Database().session() as s:
        result = await s.execute(select(exists().where(PromoCodes.code == code.upper())))
        if result.scalar():
            return None
        promo = PromoCodes(
            code=code.upper(),
            discount_type=discount_type,
            discount_value=Decimal(str(discount_value)),
            scope=promo_scope_for(category_id, item_id),
            max_uses=max_uses,
            expires_at=expires_at,
            category_id=category_id,
            item_id=item_id,
        )
        s.add(promo)
        await s.flush()
        return promo.id


async def _add_to_cart_once(user_id: int, item_name: str, promo_code: str, quantity: int) -> tuple[bool, str]:
    """One attempt at add_to_cart. See add_to_cart for semantics."""
    async with Database().session() as s:
        # Resolve to the goods id (also serves as the existence check).
        item_id = (await s.execute(
            select(Goods.id).where(Goods.name == item_name)
        )).scalar()
        if not item_id:
            return False, "item_not_found"

        existing = (await s.execute(
            select(CartItems)
            .where(CartItems.user_id == user_id, CartItems.item_id == item_id)
            .with_for_update()
        )).scalars().first()

        if existing:
            if existing.quantity + quantity > CART_MAX_QTY_PER_ITEM:
                return False, "cart_qty_max"
            existing.quantity += quantity
            if promo_code:
                # Latest applied promo wins for the whole line.
                existing.promo_code = promo_code
            return True, "success"

        # Only a new line can fill the cart up
        count = (await s.execute(
            select(sa_func.count(CartItems.id)).where(CartItems.user_id == user_id)
        )).scalar() or 0
        if count >= CART_MAX_ITEMS:
            return False, "cart_full"

        s.add(CartItems(user_id=user_id, item_id=item_id, promo_code=promo_code, quantity=quantity))
        return True, "success"


async def add_to_cart(user_id: int, item_name: str, promo_code: str = None, quantity: int = 1) -> tuple[bool, str]:
    """Add `quantity` units of an item to the user's cart.

    One row per (user, item): adding something already in the cart increments the existing line rather than inserting a duplicate.

    Returns (success, message).
    """
    if quantity < 1:
        return False, "invalid_quantity"

    try:
        return await _add_to_cart_once(user_id, item_name, promo_code, quantity)
    except IntegrityError:
        # Lost the uq_cart_item_per_user race against a concurrent add. Retry once: this attempt finds the row the winner inserted and increments it.
        try:
            return await _add_to_cart_once(user_id, item_name, promo_code, quantity)
        except IntegrityError:
            return False, "cart_conflict"


async def subscribe_to_stock(user_id: int, item_name: str) -> tuple[bool, str]:
    """Subscribe a user to the restock notification for an item.

    Idempotent: subscribing twice is a success, not an error.
    Returns (success, code).
    """
    try:
        async with Database().session() as s:
            item_id = (await s.execute(select(Goods.id).where(Goods.name == item_name))).scalar()
            if not item_id:
                return False, "item_not_found"

            already = (await s.execute(
                select(exists().where(
                    StockSubscriptions.user_id == user_id,
                    StockSubscriptions.item_id == item_id,
                ))
            )).scalar()
            if already:
                return True, "already_subscribed"

            s.add(StockSubscriptions(user_id=user_id, item_id=item_id))
    except IntegrityError:
        # Lost the uq_stock_sub_per_user_item race — the subscription now exists, which is what the caller wanted anyway.
        return True, "already_subscribed"

    return True, "subscribed"


async def create_review(user_id: int, item_name: str, rating: int, text: str = None) -> int | None:
    """Create a review. Returns ID, or None if the item is unknown, already
    reviewed, or the rating is outside 1-5.
    """
    if not isinstance(rating, int) or isinstance(rating, bool) or not 1 <= rating <= 5:
        return None
    if not item_name:
        return None

    async with Database().session() as s:
        item_id = (await s.execute(
            select(Goods.id).where(Goods.name == item_name)
        )).scalar()
        if not item_id:
            return None
        existing = (await s.execute(
            select(exists().where(
                Reviews.user_id == user_id,
                Reviews.item_id == item_id,
            ))
        )).scalar()
        if existing:
            return None
        review = Reviews(user_id=user_id, item_id=item_id, rating=rating, text=text)
        s.add(review)
        await s.flush()
        return review.id
