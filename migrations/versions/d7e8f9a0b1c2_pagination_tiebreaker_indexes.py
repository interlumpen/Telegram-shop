"""pagination tiebreaker indexes

Revision ID: d7e8f9a0b1c2
Revises: c8d9e0f1a2b3
Create Date: 2026-07-25 12:00:00.000000

Every paginated list now orders by a unique tiebreaker (``id``) after its sort
key. Without one, rows sharing a timestamp had no defined order between the
queries for page N and page N+1, so they could appear twice or not at all — most
visible in the purchases list, where one cart checkout inserts a batch of rows in
the same instant. The two-column indexes that backed the old ORDER BYs are
replaced by three-column ones; a uniformly descending sort is served by scanning
them backwards, so no DESC index is needed.
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = 'd7e8f9a0b1c2'
down_revision: Union[str, None] = 'c8d9e0f1a2b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (index name, table, columns) — the tiebreaker indexes to create.
_NEW_INDEXES = [
    ('ix_bought_goods_buyer_datetime_id', 'bought_goods', ['buyer_id', 'bought_datetime', 'id']),
    ('ix_referral_earnings_referrer_created_id', 'referral_earnings', ['referrer_id', 'created_at', 'id']),
    ('ix_referral_earnings_referral_created_id', 'referral_earnings', ['referral_id', 'created_at', 'id']),
    ('ix_referral_earnings_pair_created', 'referral_earnings', ['referrer_id', 'referral_id', 'created_at', 'id']),
    ('ix_reviews_item_created_id', 'reviews', ['item_id', 'created_at', 'id']),
    ('ix_promo_codes_created_id', 'promo_codes', ['created_at', 'id']),
]

# Two-column predecessors, now fully covered by the three-column forms above.
_SUPERSEDED_INDEXES = [
    ('ix_bought_goods_buyer_datetime', 'bought_goods'),
    ('ix_referral_earnings_referrer_created', 'referral_earnings'),
    ('ix_referral_earnings_referral_created', 'referral_earnings'),
]

def _index_names(inspector, table: str) -> set[str]:
    try:
        return {idx['name'] for idx in inspector.get_indexes(table)}
    except Exception:
        return set()


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != 'postgresql':
        return  # SQLite/test path: create_all already built these from the models.

    inspector = inspect(bind)

    for name, table, columns in _NEW_INDEXES:
        if name not in _index_names(inspector, table):
            op.create_index(name, table, columns)

    for name, table in _SUPERSEDED_INDEXES:
        if name in _index_names(inspector, table):
            op.drop_index(name, table_name=table)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != 'postgresql':
        return

    inspector = inspect(bind)

    # Restore the two-column indexes before removing what replaced them.
    if 'ix_bought_goods_buyer_datetime' not in _index_names(inspector, 'bought_goods'):
        op.create_index('ix_bought_goods_buyer_datetime', 'bought_goods',
                        ['buyer_id', 'bought_datetime'])
    for name, columns in (
        ('ix_referral_earnings_referrer_created', ['referrer_id', 'created_at']),
        ('ix_referral_earnings_referral_created', ['referral_id', 'created_at']),
    ):
        if name not in _index_names(inspector, 'referral_earnings'):
            op.create_index(name, 'referral_earnings', columns)

    for name, table, _columns in _NEW_INDEXES:
        if name in _index_names(inspector, table):
            op.drop_index(name, table_name=table)
