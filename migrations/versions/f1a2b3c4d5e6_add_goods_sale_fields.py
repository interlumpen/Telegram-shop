"""add time-limited sale fields to goods

Revision ID: f1a2b3c4d5e6
Revises: e5f6a7b8c9d0
Create Date: 2026-07-04 12:45:23.245631

Adds sale_percent (discount %) and sale_until (UTC expiry) to goods so a product
can be put on a time-limited sale. Both nullable; a sale is active only while
sale_until is in the future and sale_percent > 0.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_columns = {c['name'] for c in inspector.get_columns('goods')}

    if 'sale_percent' not in existing_columns:
        op.add_column('goods', sa.Column('sale_percent', sa.Numeric(5, 2), nullable=True))
    if 'sale_until' not in existing_columns:
        op.add_column('goods', sa.Column('sale_until', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_columns = {c['name'] for c in inspector.get_columns('goods')}

    if 'sale_until' in existing_columns:
        op.drop_column('goods', 'sale_until')
    if 'sale_percent' in existing_columns:
        op.drop_column('goods', 'sale_percent')
