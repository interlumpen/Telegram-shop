"""add cart item quantity

Revision ID: d1e2f3a4b5c6
Revises: c1d2e3f4a5b6
Create Date: 2026-07-15 10:04:11.882317

Adds cart_items.quantity so a user can buy several units of one position.

Until now duplicate (user_id, item_id) rows were possible but modelled nothing —
the cart was effectively a set. Those duplicates are collapsed into a single row
carrying the count before the unique constraint goes on, otherwise the constraint
cannot be created on a live database.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = 'd1e2f3a4b5c6'
down_revision: Union[str, None] = 'c1d2e3f4a5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(inspector, table_name, column_name):
    try:
        return any(c['name'] == column_name for c in inspector.get_columns(table_name))
    except Exception:
        return False


def _has_constraint(inspector, table_name, constraint_name):
    try:
        if any(uc['name'] == constraint_name for uc in inspector.get_unique_constraints(table_name)):
            return True
    except Exception:
        pass
    try:
        return any(cc['name'] == constraint_name for cc in inspector.get_check_constraints(table_name))
    except Exception:
        return False


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if 'cart_items' not in inspector.get_table_names():
        return

    if not _has_column(inspector, 'cart_items', 'quantity'):
        # server_default backfills existing rows implicitly...
        op.add_column(
            'cart_items',
            sa.Column('quantity', sa.Integer(), nullable=False, server_default='1'),
        )
        # ...then drop it so the DDL matches the model, which sets the default in Python.
        op.alter_column('cart_items', 'quantity', server_default=None)

    # Collapse pre-existing duplicates into one row holding the count. This must
    # happen before uq_cart_item_per_user is created or the constraint will fail.
    #
    # Postgres-only, like the rest of the chain: dsn() hardcodes postgresql+asyncpg,
    # and the constraints below would need batch_alter_table on SQLite anyway.
    op.execute("""
        UPDATE cart_items c
        SET quantity = d.n
        FROM (
            SELECT user_id, item_id, COUNT(*) AS n, MIN(id) AS keep_id
            FROM cart_items
            GROUP BY user_id, item_id
            HAVING COUNT(*) > 1
        ) d
        WHERE c.id = d.keep_id
    """)
    op.execute("""
        DELETE FROM cart_items c
        USING (
            SELECT user_id, item_id, MIN(id) AS keep_id
            FROM cart_items
            GROUP BY user_id, item_id
            HAVING COUNT(*) > 1
        ) d
        WHERE c.user_id = d.user_id
          AND c.item_id = d.item_id
          AND c.id <> d.keep_id
    """)

    inspector = inspect(bind)
    if not _has_constraint(inspector, 'cart_items', 'ck_cart_items_quantity_positive'):
        op.create_check_constraint(
            'ck_cart_items_quantity_positive', 'cart_items', 'quantity > 0',
        )
    if not _has_constraint(inspector, 'cart_items', 'uq_cart_item_per_user'):
        op.create_unique_constraint(
            'uq_cart_item_per_user', 'cart_items', ['user_id', 'item_id'],
        )


def downgrade() -> None:
    """Drop quantity and its constraints.

    Lossy by design: a row with quantity=N is not re-expanded into N duplicate
    rows. Carts are ephemeral, so the loss is harmless.
    """
    bind = op.get_bind()
    inspector = inspect(bind)

    if 'cart_items' not in inspector.get_table_names():
        return

    if _has_constraint(inspector, 'cart_items', 'uq_cart_item_per_user'):
        op.drop_constraint('uq_cart_item_per_user', 'cart_items', type_='unique')
    if _has_constraint(inspector, 'cart_items', 'ck_cart_items_quantity_positive'):
        op.drop_constraint('ck_cart_items_quantity_positive', 'cart_items', type_='check')
    if _has_column(inspector, 'cart_items', 'quantity'):
        op.drop_column('cart_items', 'quantity')
