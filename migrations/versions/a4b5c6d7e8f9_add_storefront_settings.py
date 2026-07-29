"""add storefront settings

Revision ID: a4b5c6d7e8f9
Revises: d7e8f9a0b1c2
Create Date: 2026-07-29 00:00:00.000000

Stores the reusable Telegram photo file_id for the optional /start image.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = 'a4b5c6d7e8f9'
down_revision: Union[str, None] = 'd7e8f9a0b1c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if 'storefront_settings' not in inspect(bind).get_table_names():
        op.create_table(
            'storefront_settings',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('start_image_file_id', sa.Text(), nullable=True),
            sa.CheckConstraint('id = 1', name='ck_storefront_settings_singleton'),
            sa.PrimaryKeyConstraint('id'),
        )

    exists = bind.execute(
        sa.text('SELECT 1 FROM storefront_settings WHERE id = 1')
    ).scalar()
    if not exists:
        bind.execute(
            sa.text('INSERT INTO storefront_settings (id, start_image_file_id) VALUES (1, NULL)')
        )


def downgrade() -> None:
    bind = op.get_bind()
    if 'storefront_settings' in inspect(bind).get_table_names():
        op.drop_table('storefront_settings')
