"""add reviews

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-03-13 17:03:45.125412

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = inspector.get_table_names()

    if 'reviews' not in existing_tables:
        op.create_table('reviews',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.BigInteger(), nullable=False),
            sa.Column('item_name', sa.String(length=100), nullable=False),
            sa.Column('rating', sa.Integer(), nullable=False),
            sa.Column('text', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.ForeignKeyConstraint(['user_id'], ['users.telegram_id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('user_id', 'item_name', name='uq_review_per_user_item'),
            sa.CheckConstraint('rating >= 1 AND rating <= 5', name='ck_review_rating_range'),
        )
        op.create_index('ix_reviews_user_id', 'reviews', ['user_id'])
        op.create_index('ix_reviews_item_name', 'reviews', ['item_name'])


def downgrade() -> None:
    op.drop_index('ix_reviews_item_name', table_name='reviews')
    op.drop_index('ix_reviews_user_id', table_name='reviews')
    op.drop_table('reviews')
