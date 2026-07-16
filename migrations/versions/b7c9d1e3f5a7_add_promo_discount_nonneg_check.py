"""add promo_codes check constraints: non-negative discount and single binding

Revision ID: b7c9d1e3f5a7
Revises: a3b4c5d6e7f8
Create Date: 2026-07-16 10:29:43.467295

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b7c9d1e3f5a7'
down_revision: Union[str, None] = 'a3b4c5d6e7f8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Clamp any pre-existing bad rows so the constraint can be applied, then add it.
    op.execute("UPDATE promo_codes SET discount_value = 0 WHERE discount_value < 0")
    op.create_check_constraint(
        'ck_promo_discount_nonneg',
        'promo_codes',
        'discount_value >= 0',
    )

    # A promo may bind at most one of category/item. Drop the weaker (item wins)
    # binding on any ambiguous legacy row so the constraint can be applied.
    op.execute("UPDATE promo_codes SET category_id = NULL WHERE category_id IS NOT NULL AND item_id IS NOT NULL")
    op.create_check_constraint(
        'ck_promo_single_binding',
        'promo_codes',
        'category_id IS NULL OR item_id IS NULL',
    )


def downgrade() -> None:
    op.drop_constraint('ck_promo_single_binding', 'promo_codes', type_='check')
    op.drop_constraint('ck_promo_discount_nonneg', 'promo_codes', type_='check')
