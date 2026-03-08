"""add registration_date index and referral_earnings self-referral check

Revision ID: f8b2d3a1c5e7
Revises: d4a7f2e1b3c5
Create Date: 2026-03-07 08:23:56.948532

"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = 'f8b2d3a1c5e7'
down_revision: Union[str, None] = 'd4a7f2e1b3c5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _index_exists(insp, table_name, index_name):
    try:
        return any(idx['name'] == index_name for idx in insp.get_indexes(table_name))
    except Exception:
        return False


def _check_constraint_exists(insp, table_name, constraint_name):
    try:
        for ck in insp.get_check_constraints(table_name):
            if ck.get('name') == constraint_name:
                return True
    except Exception:
        pass
    return False


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)

    # Index on users.registration_date for "today's registrations" stats queries
    if not _index_exists(insp, 'users', 'ix_users_registration_date'):
        op.create_index('ix_users_registration_date', 'users', ['registration_date'], unique=False)

    # CHECK constraint: referral_earnings.referrer_id != referral_id (prevent self-referral earnings)
    if not _check_constraint_exists(insp, 'referral_earnings', 'ck_referral_earnings_no_self_referral'):
        op.create_check_constraint(
            'ck_referral_earnings_no_self_referral',
            'referral_earnings',
            'referrer_id != referral_id'
        )


def downgrade() -> None:
    op.drop_constraint('ck_referral_earnings_no_self_referral', 'referral_earnings', type_='check')
    op.drop_index('ix_users_registration_date', table_name='users')
