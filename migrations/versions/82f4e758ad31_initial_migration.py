"""Initial migration

Revision ID: 82f4e758ad31
Revises: 
Create Date: 2024-11-29 18:48:35.509201

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '82f4e758ad31'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('categories',
                    sa.Column('name', sa.String(length=100), nullable=False),
                    sa.PrimaryKeyConstraint('name'),
                    sa.UniqueConstraint('name')
                    )
    op.create_table('configuration',
                    sa.Column('key', sa.String(length=50), nullable=False),
                    sa.Column('value', sa.Text(), nullable=True),
                    sa.PrimaryKeyConstraint('key')
                    )
    op.create_table('roles',
                    sa.Column('id', sa.Integer(), nullable=False),
                    sa.Column('name', sa.String(length=64), nullable=True),
                    sa.Column('default', sa.Boolean(), nullable=True),
                    sa.Column('permissions', sa.Integer(), nullable=True),
                    sa.PrimaryKeyConstraint('id'),
                    sa.UniqueConstraint('name')
                    )
    op.create_index(op.f('ix_roles_default'), 'roles', ['default'], unique=False)
    op.create_table('goods',
                    sa.Column('name', sa.String(length=100), nullable=False),
                    sa.Column('price', sa.BigInteger(), nullable=False),
                    sa.Column('description', sa.Text(), nullable=False),
                    sa.Column('category_name', sa.String(length=100), nullable=False),
                    sa.ForeignKeyConstraint(['category_name'], ['categories.name'], ),
                    sa.PrimaryKeyConstraint('name'),
                    sa.UniqueConstraint('name')
                    )
    op.create_table('users',
                    sa.Column('telegram_id', sa.BigInteger(), nullable=False),
                    sa.Column('role_id', sa.Integer(), nullable=True),
                    sa.Column('balance', sa.BigInteger(), nullable=False),
                    sa.Column('referral_id', sa.BigInteger(), nullable=True),
                    sa.Column('registration_date', sa.VARCHAR(), nullable=False),
                    sa.ForeignKeyConstraint(['role_id'], ['roles.id'], ),
                    sa.PrimaryKeyConstraint('telegram_id'),
                    sa.UniqueConstraint('telegram_id')
                    )
    op.create_table('bought_goods',
                    sa.Column('id', sa.Integer(), nullable=False),
                    sa.Column('item_name', sa.String(length=100), nullable=False),
                    sa.Column('value', sa.Text(), nullable=False),
                    sa.Column('price', sa.BigInteger(), nullable=False),
                    sa.Column('buyer_id', sa.BigInteger(), nullable=False),
                    sa.Column('bought_datetime', sa.VARCHAR(), nullable=False),
                    sa.Column('unique_id', sa.BigInteger(), nullable=False),
                    sa.ForeignKeyConstraint(['buyer_id'], ['users.telegram_id'], ),
                    sa.PrimaryKeyConstraint('id'),
                    sa.UniqueConstraint('unique_id')
                    )
    op.create_table('item_values',
                    sa.Column('id', sa.Integer(), nullable=False),
                    sa.Column('item_name', sa.String(length=100), nullable=False),
                    sa.Column('value', sa.Text(), nullable=True),
                    sa.Column('is_infinity', sa.Boolean(), nullable=False),
                    sa.ForeignKeyConstraint(['item_name'], ['goods.name'], ),
                    sa.PrimaryKeyConstraint('id')
                    )
    op.create_table('operations',
                    sa.Column('id', sa.Integer(), nullable=False),
                    sa.Column('user_id', sa.BigInteger(), nullable=False),
                    sa.Column('operation_value', sa.BigInteger(), nullable=False),
                    sa.Column('operation_time', sa.VARCHAR(), nullable=False),
                    sa.ForeignKeyConstraint(['user_id'], ['users.telegram_id'], ),
                    sa.PrimaryKeyConstraint('id')
                    )
    op.create_table('unfinished_operations',
                    sa.Column('id', sa.Integer(), nullable=False),
                    sa.Column('user_id', sa.BigInteger(), nullable=False),
                    sa.Column('operation_value', sa.BigInteger(), nullable=False),
                    sa.Column('operation_id', sa.String(length=500), nullable=False),
                    sa.ForeignKeyConstraint(['user_id'], ['users.telegram_id'], ),
                    sa.PrimaryKeyConstraint('id')
                    )
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('unfinished_operations')
    op.drop_table('operations')
    op.drop_table('item_values')
    op.drop_table('bought_goods')
    op.drop_table('users')
    op.drop_table('goods')
    op.drop_index(op.f('ix_roles_default'), table_name='roles')
    op.drop_table('roles')
    op.drop_table('configuration')
    op.drop_table('categories')
    # ### end Alembic commands ###
