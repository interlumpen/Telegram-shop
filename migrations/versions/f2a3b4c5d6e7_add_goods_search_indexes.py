"""add goods search indexes

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-07-15 14:09:33.017264

Trigram GIN indexes backing the catalog search (name ILIKE %q% OR description
ILIKE %q%). Postgres-only and guarded: the models deliberately do NOT declare
these, because the test suite builds the schema on SQLite via create_all.

Two separate indexes rather than one composite: the query ORs two columns, and
Postgres resolves that with a BitmapOr across both.
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = 'f2a3b4c5d6e7'
down_revision: Union[str, None] = 'e1f2a3b4c5d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _index_exists(inspector, table_name, index_name):
    try:
        return any(idx['name'] == index_name for idx in inspector.get_indexes(table_name))
    except Exception:
        return False


def _ensure_pg_trgm(bind) -> bool:
    """Install pg_trgm, returning False if we lack the privilege.

    CREATE EXTENSION needs superuser on most managed Postgres. A failure here
    must not break the migration chain, so it runs inside a SAVEPOINT: in
    Postgres any error aborts the whole transaction, and without the savepoint
    every subsequent statement would fail with "current transaction is aborted".
    """
    already = bind.exec_driver_sql(
        "SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'"
    ).scalar()
    if already:
        return True

    nested = bind.begin_nested()
    try:
        bind.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        nested.commit()
        return True
    except Exception:
        nested.rollback()
        print(
            "WARNING: could not create the pg_trgm extension (needs superuser). "
            "Catalog search will still work, but falls back to a sequential scan. "
            "Install it manually and re-run this revision to get the indexes."
        )
        return False


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != 'postgresql':
        return  # SQLite/test path: a plain LIKE scan is fine at test scale.

    if not _ensure_pg_trgm(bind):
        return

    inspector = inspect(bind)
    if not _index_exists(inspector, 'goods', 'ix_goods_name_trgm'):
        op.execute("CREATE INDEX ix_goods_name_trgm ON goods USING gin (name gin_trgm_ops)")
    if not _index_exists(inspector, 'goods', 'ix_goods_description_trgm'):
        op.execute("CREATE INDEX ix_goods_description_trgm ON goods USING gin (description gin_trgm_ops)")


def downgrade() -> None:
    if op.get_bind().dialect.name != 'postgresql':
        return
    op.execute("DROP INDEX IF EXISTS ix_goods_description_trgm")
    op.execute("DROP INDEX IF EXISTS ix_goods_name_trgm")
    # pg_trgm is left installed: other objects may depend on it.
