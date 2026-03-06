"""Switch money to Numeric(12,2), dates to DateTime, add FKs & indexes

Revision ID: 3f9d1b7a4a6c
Revises: a2e0ad4f2c8d
Create Date: 2025-08-08 12:00:00
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text

# revision identifiers, used by Alembic.
revision = "3f9d1b7a4a6c"
down_revision = "a2e0ad4f2c8d"
branch_labels = None
depends_on = None


def index_exists(inspector, table_name, index_name):
    """Check if the index exists"""
    try:
        indexes = inspector.get_indexes(table_name)
        return any(idx['name'] == index_name for idx in indexes)
    except Exception:
        return False


def constraint_exists(inspector, table_name, constraint_name):
    """Check if a constraint exists"""
    try:
        fks = inspector.get_foreign_keys(table_name)
        if any(fk['name'] == constraint_name for fk in fks):
            return True

        uks = inspector.get_unique_constraints(table_name)
        if any(uk['name'] == constraint_name for uk in uks):
            return True

        return False
    except Exception:
        return False


def clean_datetime_data():
    """Clean up incorrect date data before conversion"""
    connection = op.get_bind()

    connection.execute(text("""
                            UPDATE bought_goods
                            SET bought_datetime = '2024-01-01 00:00:00'
                            WHERE bought_datetime::text = '' 
           OR bought_datetime IS NULL 
           OR LENGTH(TRIM(bought_datetime::text)) = 0
                            """))

    connection.execute(text("""
                            UPDATE operations
                            SET operation_time = '2024-01-01 00:00:00'
                            WHERE operation_time::text = '' 
           OR operation_time IS NULL 
           OR LENGTH(TRIM(operation_time::text)) = 0
                            """))


def _column_exists(conn, table_name: str, column_name: str) -> bool:
    insp = inspect(conn)
    if table_name not in insp.get_table_names():
        return False
    columns = [c['name'] for c in insp.get_columns(table_name)]
    return column_name in columns


def _col_is_numeric(conn, table_name: str, column_name: str) -> bool:
    insp = inspect(conn)
    for col in insp.get_columns(table_name):
        if col['name'] == column_name:
            return isinstance(col['type'], sa.Numeric)
    return False


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    # Skip if already migrated (balance is already Numeric or table structure changed)
    if _col_is_numeric(bind, "users", "balance"):
        return

    clean_datetime_data()

    # USERS
    with op.batch_alter_table("users", schema=None) as batch:
        batch.alter_column(
            "registration_date",
            existing_type=sa.VARCHAR(),
            type_=sa.DateTime(timezone=True),
            existing_nullable=False,
            postgresql_using="registration_date::timestamptz",
            server_default=sa.text("CURRENT_TIMESTAMP"),
        )
        batch.alter_column(
            "balance",
            existing_type=sa.BigInteger(),
            type_=sa.Numeric(12, 2),
            existing_nullable=False,
            server_default="0",
        )

        if not index_exists(inspector, "users", "ix_users_role_id"):
            batch.create_index("ix_users_role_id", ["role_id"], unique=False)

        if not index_exists(inspector, "users", "ix_users_referral_id"):
            batch.create_index("ix_users_referral_id", ["referral_id"], unique=False)

        if not constraint_exists(inspector, "users", "fk_users_referral_id_users"):
            batch.create_foreign_key(
                "fk_users_referral_id_users",
                referent_table="users",
                local_cols=["referral_id"],
                remote_cols=["telegram_id"],
                ondelete="SET NULL",
            )

        if not constraint_exists(inspector, "users", "fk_users_role_id_roles"):
            batch.create_foreign_key(
                "fk_users_role_id_roles",
                referent_table="roles",
                local_cols=["role_id"],
                remote_cols=["id"],
                ondelete="RESTRICT",
            )

    # GOODS (direct ops — batch mode can recreate the table via model metadata and lose columns)
    op.alter_column(
        "goods", "price",
        existing_type=sa.BigInteger(),
        type_=sa.Numeric(12, 2),
        existing_nullable=False,
        postgresql_using="price::numeric(12,2)",
    )

    if not index_exists(inspector, "goods", "ix_goods_category_name"):
        columns = [c['name'] for c in inspector.get_columns("goods")]
        if "category_name" in columns:
            op.create_index("ix_goods_category_name", "goods", ["category_name"], unique=False)

    # ITEM_VALUES (direct ops — batch mode can lose columns renamed in later migrations)
    columns = [c['name'] for c in inspector.get_columns("item_values")]
    item_col = "item_name" if "item_name" in columns else "item_id"

    if not constraint_exists(inspector, "item_values", "uq_item_value_per_item"):
        op.create_unique_constraint("uq_item_value_per_item", "item_values", [item_col, "value"])

    if not index_exists(inspector, "item_values", "ix_item_values_item_inf"):
        op.create_index("ix_item_values_item_inf", "item_values", [item_col, "is_infinity"], unique=False)

    # BOUGHT_GOODS
    with op.batch_alter_table("bought_goods", schema=None) as batch:
        batch.alter_column(
            "bought_datetime",
            existing_type=sa.VARCHAR(),
            type_=sa.DateTime(timezone=True),
            existing_nullable=False,
            postgresql_using="bought_datetime::timestamptz",
            server_default=sa.text("CURRENT_TIMESTAMP"),
        )
        batch.alter_column(
            "price",
            existing_type=sa.BigInteger(),
            type_=sa.Numeric(12, 2),
            existing_nullable=False,
        )

        if not index_exists(inspector, "bought_goods", "ix_bought_goods_buyer_id"):
            batch.create_index("ix_bought_goods_buyer_id", ["buyer_id"], unique=False)

    if not index_exists(inspector, "bought_goods", "ix_bought_goods_buyer_time"):
        op.create_index(
            "ix_bought_goods_buyer_time",
            "bought_goods",
            ["buyer_id", sa.text("bought_datetime DESC")],
            unique=False,
        )

    # OPERATIONS
    with op.batch_alter_table("operations", schema=None) as batch:
        batch.alter_column(
            "operation_time",
            existing_type=sa.VARCHAR(),
            type_=sa.DateTime(timezone=True),
            existing_nullable=False,
            postgresql_using="operation_time::timestamptz",
            server_default=sa.text("CURRENT_TIMESTAMP"),
        )
        batch.alter_column(
            "operation_value",
            existing_type=sa.BigInteger(),
            type_=sa.Numeric(12, 2),
            existing_nullable=False,
        )

        if not index_exists(inspector, "operations", "ix_operations_user_id"):
            batch.create_index("ix_operations_user_id", ["user_id"], unique=False)

    if not index_exists(inspector, "operations", "ix_operations_user_time"):
        op.create_index(
            "ix_operations_user_time",
            "operations",
            ["user_id", sa.text("operation_time DESC")],
            unique=False,
        )

    # UNFINISHED_OPERATIONS
    existing_tables = inspector.get_table_names()
    if "unfinished_operations" in existing_tables:
        with op.batch_alter_table("unfinished_operations", schema=None) as batch:
            batch.alter_column(
                "operation_value",
                existing_type=sa.BigInteger(),
                type_=sa.Numeric(12, 2),
                existing_nullable=False,
            )
            batch.alter_column(
                "operation_id",
                existing_type=sa.String(length=500),
                type_=sa.String(length=128),
                existing_nullable=False,
            )

            columns = [col['name'] for col in inspector.get_columns("unfinished_operations")]
            if "created_at" not in columns:
                batch.add_column(
                    sa.Column(
                        "created_at",
                        sa.DateTime(timezone=True),
                        nullable=False,
                        server_default=sa.text("CURRENT_TIMESTAMP"),
                    )
                )

            if not index_exists(inspector, "unfinished_operations", "ix_unfinished_operations_user_id"):
                batch.create_index("ix_unfinished_operations_user_id", ["user_id"], unique=False)

            if not index_exists(inspector, "unfinished_operations", "ix_unfinished_operations_operation_id"):
                batch.create_index("ix_unfinished_operations_operation_id", ["operation_id"], unique=True)


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = inspector.get_table_names()

    # UNFINISHED_OPERATIONS
    if "unfinished_operations" in existing_tables:
        if index_exists(inspector, "unfinished_operations", "ix_unfinished_operations_operation_id"):
            with op.batch_alter_table("unfinished_operations", schema=None) as batch:
                batch.drop_index("ix_unfinished_operations_operation_id")

        if index_exists(inspector, "unfinished_operations", "ix_unfinished_operations_user_id"):
            with op.batch_alter_table("unfinished_operations", schema=None) as batch:
                batch.drop_index("ix_unfinished_operations_user_id")

        columns = [col['name'] for col in inspector.get_columns("unfinished_operations")]
        if "created_at" in columns:
            with op.batch_alter_table("unfinished_operations", schema=None) as batch:
                batch.drop_column("created_at")

        with op.batch_alter_table("unfinished_operations", schema=None) as batch:
            batch.alter_column(
                "operation_id",
                existing_type=sa.String(length=128),
                type_=sa.String(length=500),
                existing_nullable=False,
            )
            batch.alter_column(
                "operation_value",
                existing_type=sa.Numeric(12, 2),
                type_=sa.BigInteger(),
                existing_nullable=False,
            )

    # OPERATIONS
    if index_exists(inspector, "operations", "ix_operations_user_time"):
        op.drop_index("ix_operations_user_time", table_name="operations")

    with op.batch_alter_table("operations", schema=None) as batch:
        if index_exists(inspector, "operations", "ix_operations_user_id"):
            batch.drop_index("ix_operations_user_id")
        batch.alter_column(
            "operation_value",
            existing_type=sa.Numeric(12, 2),
            type_=sa.BigInteger(),
            existing_nullable=False,
        )
        batch.alter_column(
            "operation_time",
            existing_type=sa.DateTime(timezone=True),
            type_=sa.VARCHAR(),
            existing_nullable=False,
        )

    # BOUGHT_GOODS
    if index_exists(inspector, "bought_goods", "ix_bought_goods_buyer_time"):
        op.drop_index("ix_bought_goods_buyer_time", table_name="bought_goods")

    with op.batch_alter_table("bought_goods", schema=None) as batch:
        if index_exists(inspector, "bought_goods", "ix_bought_goods_buyer_id"):
            batch.drop_index("ix_bought_goods_buyer_id")
        batch.alter_column(
            "price",
            existing_type=sa.Numeric(12, 2),
            type_=sa.BigInteger(),
            existing_nullable=False,
        )
        batch.alter_column(
            "bought_datetime",
            existing_type=sa.DateTime(timezone=True),
            type_=sa.VARCHAR(),
            existing_nullable=False,
        )

    # ITEM_VALUES (direct ops)
    if index_exists(inspector, "item_values", "ix_item_values_item_inf"):
        op.drop_index("ix_item_values_item_inf", table_name="item_values")
    if constraint_exists(inspector, "item_values", "uq_item_value_per_item"):
        op.drop_constraint("uq_item_value_per_item", "item_values", type_="unique")

    # GOODS (direct ops)
    if index_exists(inspector, "goods", "ix_goods_category_name"):
        op.drop_index("ix_goods_category_name", table_name="goods")
    op.alter_column(
        "goods", "price",
        existing_type=sa.Numeric(12, 2),
        type_=sa.BigInteger(),
        existing_nullable=False,
        postgresql_using="price::bigint",
    )

    # USERS
    if constraint_exists(inspector, "users", "fk_users_role_id_roles"):
        op.drop_constraint("fk_users_role_id_roles", "users", type_="foreignkey")
    if constraint_exists(inspector, "users", "fk_users_referral_id_users"):
        op.drop_constraint("fk_users_referral_id_users", "users", type_="foreignkey")

    with op.batch_alter_table("users", schema=None) as batch:
        if index_exists(inspector, "users", "ix_users_referral_id"):
            batch.drop_index("ix_users_referral_id")
        if index_exists(inspector, "users", "ix_users_role_id"):
            batch.drop_index("ix_users_role_id")
        batch.alter_column(
            "balance",
            existing_type=sa.Numeric(12, 2),
            type_=sa.BigInteger(),
            existing_nullable=False,
        )
        batch.alter_column(
            "registration_date",
            existing_type=sa.DateTime(timezone=True),
            type_=sa.VARCHAR(),
            existing_nullable=False,
        )
