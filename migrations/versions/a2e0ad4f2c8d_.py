"""empty message

Revision ID: a2e0ad4f2c8d
Revises: 82f4e758ad31
Create Date: 2024-11-29 18:49:57.378612

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a2e0ad4f2c8d'
down_revision: Union[str, None] = '82f4e758ad31'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('configuration')
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('configuration',
                    sa.Column('key', sa.VARCHAR(length=50), nullable=False),
                    sa.Column('value', sa.TEXT(), nullable=True),
                    sa.PrimaryKeyConstraint('key')
                    )
    # ### end Alembic commands ###