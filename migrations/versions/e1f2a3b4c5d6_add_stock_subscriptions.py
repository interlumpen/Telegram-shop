"""add stock subscriptions

Revision ID: e1f2a3b4c5d6
Revises: d1e2f3a4b5c6
Create Date: 2026-07-15 12:45:52.410883

Backs the "notify me when back in stock" button on an out-of-stock item card.
Rows are consumed by the notifier once the message is sent.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = 'e1f2a3b4c5d6'
down_revision: Union[str, None] = 'd1e2f3a4b5c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _index_exists(inspector, table_name, index_name):
    try:
        return any(idx['name'] == index_name for idx in inspector.get_indexes(table_name))
    except Exception:
        return False


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if 'stock_subscriptions' not in inspector.get_table_names():
        op.create_table(
            'stock_subscriptions',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.BigInteger(), nullable=False),
            sa.Column('item_id', sa.Integer(), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True),
                      server_default=sa.text('now()'), nullable=False),
            sa.ForeignKeyConstraint(['user_id'], ['users.telegram_id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['item_id'], ['goods.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('user_id', 'item_id', name='uq_stock_sub_per_user_item'),
        )

    inspector = inspect(bind)
    if not _index_exists(inspector, 'stock_subscriptions', 'ix_stock_subscriptions_user_id'):
        op.create_index('ix_stock_subscriptions_user_id', 'stock_subscriptions', ['user_id'])
    if not _index_exists(inspector, 'stock_subscriptions', 'ix_stock_subscriptions_item_id'):
        op.create_index('ix_stock_subscriptions_item_id', 'stock_subscriptions', ['item_id'])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if 'stock_subscriptions' not in inspector.get_table_names():
        return

    if _index_exists(inspector, 'stock_subscriptions', 'ix_stock_subscriptions_item_id'):
        op.drop_index('ix_stock_subscriptions_item_id', table_name='stock_subscriptions')
    if _index_exists(inspector, 'stock_subscriptions', 'ix_stock_subscriptions_user_id'):
        op.drop_index('ix_stock_subscriptions_user_id', table_name='stock_subscriptions')
    op.drop_table('stock_subscriptions')
