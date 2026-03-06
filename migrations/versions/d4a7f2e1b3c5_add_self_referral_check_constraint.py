"""add self-referral check constraint

Revision ID: d4a7f2e1b3c5
Revises: b1a3c5d7e9f0
Create Date: 2026-03-06 19:47:23.097653

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd4a7f2e1b3c5'
down_revision: Union[str, None] = 'b1a3c5d7e9f0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_check_constraint(
        'ck_users_no_self_referral',
        'users',
        'referral_id != telegram_id'
    )


def downgrade() -> None:
    op.drop_constraint('ck_users_no_self_referral', 'users', type_='check')
