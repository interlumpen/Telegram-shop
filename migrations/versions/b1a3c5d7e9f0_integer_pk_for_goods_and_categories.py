"""integer pk for goods and categories

Revision ID: b1a3c5d7e9f0
Revises: 5ec59540ad4f
Create Date: 2026-03-02 22:14:07.183065

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = 'b1a3c5d7e9f0'
down_revision: Union[str, None] = '5ec59540ad4f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(conn, table_name: str) -> bool:
    insp = inspect(conn)
    return table_name in insp.get_table_names()


def _column_exists(conn, table_name: str, column_name: str) -> bool:
    insp = inspect(conn)
    if table_name not in insp.get_table_names():
        return False
    columns = [c['name'] for c in insp.get_columns(table_name)]
    return column_name in columns


def upgrade() -> None:
    conn = op.get_bind()

    # Skip if already migrated (idempotent)
    if _column_exists(conn, 'categories', 'id'):
        return

    op.create_table(
        'categories_new',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('name', sa.String(100), unique=True, nullable=False),
    )

    op.create_table(
        'goods_new',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('name', sa.String(100), unique=True, nullable=False),
        sa.Column('price', sa.Numeric(12, 2), nullable=False),
        sa.Column('description', sa.Text, nullable=False),
        sa.Column('category_id', sa.Integer, sa.ForeignKey('categories_new.id', ondelete='CASCADE'), nullable=False),
    )
    op.create_index('ix_goods_new_category_id', 'goods_new', ['category_id'])

    op.create_table(
        'item_values_new',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('item_id', sa.Integer, sa.ForeignKey('goods_new.id', ondelete='CASCADE'), nullable=False),
        sa.Column('value', sa.Text, nullable=True),
        sa.Column('is_infinity', sa.Boolean, nullable=False),
        sa.UniqueConstraint('item_id', 'value', name='uq_item_value_per_item_new'),
    )
    op.create_index('ix_item_values_new_item_id', 'item_values_new', ['item_id'])
    op.create_index('ix_item_values_new_item_inf', 'item_values_new', ['item_id', 'is_infinity'])

    op.execute("""
        INSERT INTO categories_new (name)
        SELECT name FROM categories
    """)

    op.execute("""
        INSERT INTO goods_new (name, price, description, category_id)
        SELECT g.name, g.price, g.description, cn.id
        FROM goods g
        JOIN categories_new cn ON cn.name = g.category_name
    """)

    op.execute("""
        INSERT INTO item_values_new (item_id, value, is_infinity)
        SELECT gn.id, iv.value, iv.is_infinity
        FROM item_values iv
        JOIN goods_new gn ON gn.name = iv.item_name
    """)

    op.drop_table('item_values')
    op.drop_table('goods')
    op.drop_table('categories')

    op.rename_table('categories_new', 'categories')
    op.rename_table('goods_new', 'goods')
    op.rename_table('item_values_new', 'item_values')


def downgrade() -> None:
    conn = op.get_bind()

    # Recreate old string-PK tables
    op.create_table(
        'categories_old',
        sa.Column('name', sa.String(100), primary_key=True),
    )

    op.create_table(
        'goods_old',
        sa.Column('name', sa.String(100), primary_key=True),
        sa.Column('price', sa.Numeric(12, 2), nullable=False),
        sa.Column('description', sa.Text, nullable=False),
        sa.Column('category_name', sa.String(100),
                   sa.ForeignKey('categories_old.name', ondelete='CASCADE', onupdate='CASCADE'),
                   nullable=False),
    )

    op.create_table(
        'item_values_old',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('item_name', sa.String(100),
                   sa.ForeignKey('goods_old.name', ondelete='CASCADE', onupdate='CASCADE'),
                   nullable=False),
        sa.Column('value', sa.Text, nullable=True),
        sa.Column('is_infinity', sa.Boolean, nullable=False),
        sa.UniqueConstraint('item_name', 'value', name='uq_item_value_per_item_old'),
    )

    # Copy data back
    op.execute("INSERT INTO categories_old (name) SELECT name FROM categories")

    op.execute("""
        INSERT INTO goods_old (name, price, description, category_name)
        SELECT g.name, g.price, g.description, c.name
        FROM goods g JOIN categories c ON c.id = g.category_id
    """)

    op.execute("""
        INSERT INTO item_values_old (item_name, value, is_infinity)
        SELECT g.name, iv.value, iv.is_infinity
        FROM item_values iv JOIN goods g ON g.id = iv.item_id
    """)

    op.drop_table('item_values')
    op.drop_table('goods')
    op.drop_table('categories')

    op.rename_table('categories_old', 'categories')
    op.rename_table('goods_old', 'goods')
    op.rename_table('item_values_old', 'item_values')
