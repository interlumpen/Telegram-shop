"""add promo codes

Revision ID: a1b2c3d4e5f6
Revises: f8b2d3a1c5e7
Create Date: 2026-03-09 23:05:42.294758

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'f8b2d3a1c5e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = inspector.get_table_names()

    if 'promo_codes' not in existing_tables:
        op.create_table('promo_codes',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('code', sa.String(length=50), nullable=False),
            sa.Column('discount_type', sa.String(length=10), nullable=False),
            sa.Column('discount_value', sa.Numeric(precision=12, scale=2), nullable=False),
            sa.Column('max_uses', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('current_uses', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('category_id', sa.Integer(), nullable=True),
            sa.Column('item_id', sa.Integer(), nullable=True),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.ForeignKeyConstraint(['category_id'], ['categories.id'], ondelete='SET NULL'),
            sa.ForeignKeyConstraint(['item_id'], ['goods.id'], ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('ix_promo_codes_code', 'promo_codes', ['code'], unique=True)
        op.create_index('ix_promo_codes_is_active', 'promo_codes', ['is_active'])

    if 'promo_code_usages' not in existing_tables:
        op.create_table('promo_code_usages',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('promo_id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.BigInteger(), nullable=False),
            sa.Column('used_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.ForeignKeyConstraint(['promo_id'], ['promo_codes.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['user_id'], ['users.telegram_id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('promo_id', 'user_id', name='uq_promo_usage_per_user'),
        )


def downgrade() -> None:
    op.drop_table('promo_code_usages')
    op.drop_index('ix_promo_codes_is_active', table_name='promo_codes')
    op.drop_index('ix_promo_codes_code', table_name='promo_codes')
    op.drop_table('promo_codes')
