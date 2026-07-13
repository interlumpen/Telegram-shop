"""cart_items and reviews reference goods by FK instead of item_name string

Revision ID: c1d2e3f4a5b6
Revises: f1a2b3c4d5e6
Create Date: 2026-07-13 21:37:11.415328

Replaces the free-form item_name string on cart_items and reviews with a real
item_id FK to goods(id) ON DELETE CASCADE. item_id is backfilled from the current
name; rows whose name no longer matches a goods row (orphans left by a delete)
are removed. For reviews the uniqueness is swapped from (user_id, item_name) to
(user_id, item_id). After this, renaming a product keeps carts/reviews linked and
deleting it cascade-removes them — no manual name fan-out, no orphan rows.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = 'c1d2e3f4a5b6'
down_revision: Union[str, None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = ('cart_items', 'reviews')


def _has_column(inspector, table: str, column: str) -> bool:
    return column in {c['name'] for c in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    for table in _TABLES:
        if _has_column(inspector, table, 'item_id'):
            continue  # already migrated

        op.add_column(table, sa.Column('item_id', sa.Integer(), nullable=True))
        # Backfill from the current name (goods.name is unique -> at most one match).
        op.execute(f"""
            UPDATE {table} AS t
            SET item_id = g.id
            FROM goods g
            WHERE g.name = t.item_name
        """)
        # Drop orphans whose name no longer matches a goods row.
        op.execute(f"DELETE FROM {table} WHERE item_id IS NULL")

        op.alter_column(table, 'item_id', existing_type=sa.Integer(), nullable=False)
        op.create_index(f'ix_{table}_item_id', table, ['item_id'])
        op.create_foreign_key(
            f'{table}_item_id_fkey', table, 'goods',
            ['item_id'], ['id'], ondelete='CASCADE',
        )

    # reviews: swap uniqueness (user_id, item_name) -> (user_id, item_id).
    op.execute("ALTER TABLE reviews DROP CONSTRAINT IF EXISTS uq_review_per_user_item")
    op.execute("DROP INDEX IF EXISTS ix_reviews_item_name")
    op.create_unique_constraint('uq_review_per_user_item', 'reviews', ['user_id', 'item_id'])

    for table in _TABLES:
        if _has_column(inspector, table, 'item_name'):
            op.drop_column(table, 'item_name')


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    op.execute("ALTER TABLE reviews DROP CONSTRAINT IF EXISTS uq_review_per_user_item")

    for table in _TABLES:
        if not _has_column(inspector, table, 'item_name'):
            op.add_column(table, sa.Column('item_name', sa.String(length=100), nullable=True))
            op.execute(f"""
                UPDATE {table} AS t
                SET item_name = g.name
                FROM goods g
                WHERE g.id = t.item_id
            """)
            op.alter_column(table, 'item_name', existing_type=sa.String(length=100), nullable=False)

        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {table}_item_id_fkey")
        op.execute(f"DROP INDEX IF EXISTS ix_{table}_item_id")
        if _has_column(inspector, table, 'item_id'):
            op.drop_column(table, 'item_id')

    op.create_index('ix_reviews_item_name', 'reviews', ['item_name'])
    op.create_unique_constraint('uq_review_per_user_item', 'reviews', ['user_id', 'item_name'])
