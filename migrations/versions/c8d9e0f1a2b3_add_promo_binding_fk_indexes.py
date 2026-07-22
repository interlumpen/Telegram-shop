"""add promo binding fk indexes

Revision ID: c8d9e0f1a2b3
Revises: b7c9d1e3f5a7
Create Date: 2026-07-20 13:44:52.572843

promo_codes.category_id / item_id are ON DELETE SET NULL foreign keys with no
index: every Goods/Categories delete forced a sequential scan of promo_codes
to find referencing rows, and "promos bound to this item/category" lookups did
the same. Matches the index=True now declared on the model.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c8d9e0f1a2b3'
down_revision: Union[str, None] = 'b7c9d1e3f5a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index('ix_promo_codes_category_id', 'promo_codes', ['category_id'])
    op.create_index('ix_promo_codes_item_id', 'promo_codes', ['item_id'])


def downgrade() -> None:
    op.drop_index('ix_promo_codes_item_id', table_name='promo_codes')
    op.drop_index('ix_promo_codes_category_id', table_name='promo_codes')
