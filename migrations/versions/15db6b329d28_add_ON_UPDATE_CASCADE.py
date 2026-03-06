"""add ON UPDATE CASCADE

Revision ID: 15db6b329d28
Revises: 8xk049bo647i
Create Date: 2025-08-08 12:34:56
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = "15db6b329d28"
down_revision = "8xk049bo647i"
branch_labels = None
depends_on = None


def find_fk_name_sa(conn, table, local_col, ref_table=None):
    insp = inspect(conn)
    for fk in insp.get_foreign_keys(table):
        if local_col in fk.get("constrained_columns", []):
            if not ref_table or fk.get("referred_table") == ref_table:
                return fk.get("name")
    return None


def _column_exists(conn, table_name: str, column_name: str) -> bool:
    insp = inspect(conn)
    if table_name not in insp.get_table_names():
        return False
    columns = [c['name'] for c in insp.get_columns(table_name)]
    return column_name in columns


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name not in ("postgresql", "mysql"):
        return

    # Skip if already migrated to integer PKs (category_name no longer exists)
    if not _column_exists(bind, "goods", "category_name"):
        return

    # goods.category_name → categories.name
    old_fk_goods = find_fk_name_sa(bind, "goods", "category_name", ref_table="categories")
    if old_fk_goods:
        op.drop_constraint(old_fk_goods, "goods", type_="foreignkey")

    op.create_foreign_key(
        "goods_category_name_fkey",
        source_table="goods",
        referent_table="categories",
        local_cols=["category_name"],
        remote_cols=["name"],
        ondelete="CASCADE",
        onupdate="CASCADE",
    )

    # item_values.item_name → goods.name
    old_fk_itemvalues = find_fk_name_sa(bind, "item_values", "item_name", ref_table="goods")
    if old_fk_itemvalues:
        op.drop_constraint(old_fk_itemvalues, "item_values", type_="foreignkey")

    op.create_foreign_key(
        "item_values_item_name_fkey",
        source_table="item_values",
        referent_table="goods",
        local_cols=["item_name"],
        remote_cols=["name"],
        ondelete="CASCADE",
        onupdate="CASCADE",
    )


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name not in ("postgresql", "mysql"):
        return

    # Откатываем до варианта БЕЗ ON UPDATE CASCADE
    op.drop_constraint("goods_category_name_fkey", "goods", type_="foreignkey")
    op.create_foreign_key(
        "goods_category_name_fkey",
        source_table="goods",
        referent_table="categories",
        local_cols=["category_name"],
        remote_cols=["name"],
        ondelete="CASCADE",
    )

    op.drop_constraint("item_values_item_name_fkey", "item_values", type_="foreignkey")
    op.create_foreign_key(
        "item_values_item_name_fkey",
        source_table="item_values",
        referent_table="goods",
        local_cols=["item_name"],
        remote_cols=["name"],
        ondelete="CASCADE",
    )
