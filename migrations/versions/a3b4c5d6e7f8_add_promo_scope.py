"""add promo code scope discriminator

Revision ID: a3b4c5d6e7f8
Revises: f2a3b4c5d6e7
Create Date: 2026-07-16 00:35:07.552914

promo_codes.category_id and item_id are ON DELETE SET NULL, and promo_rule_error
guarded with `if promo.category_id and ...`. Deleting the bound category erased
the binding, the guard was skipped, and a promo scoped to one category silently
became valid on every product in the shop.

`scope` records the intent that the FK destroys, so a promo whose target is gone
stays scoped and keeps rejecting everything.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = 'a3b4c5d6e7f8'
down_revision: Union[str, None] = 'f2a3b4c5d6e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_check(inspector, table_name: str, name: str) -> bool:
    try:
        return any(c['name'] == name for c in inspector.get_check_constraints(table_name))
    except Exception:
        # Check-constraint reflection is unreliable on SQLite; the guard only
        # has to hold on Postgres, which is the only dialect migrations run on.
        return False


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if 'promo_codes' not in inspector.get_table_names():
        return

    if 'scope' not in {c['name'] for c in inspector.get_columns('promo_codes')}:
        # server_default makes adding a NOT NULL column safe on a populated
        # table in one statement, and covers raw INSERTs afterwards.
        op.add_column(
            'promo_codes',
            sa.Column('scope', sa.String(16), nullable=False, server_default='global'),
        )

    # Backfill item-first, matching promo_scope_for() and the guard's precedence.
    # Rows with neither binding are already 'global' from the server_default.
    op.execute("UPDATE promo_codes SET scope = 'item' WHERE item_id IS NOT NULL")
    op.execute(
        "UPDATE promo_codes SET scope = 'category' "
        "WHERE item_id IS NULL AND category_id IS NOT NULL"
    )

    # The schema allows both bindings at once and the guard ANDs them, but scope
    # cannot express AND. The guard stays additive so these rows keep their
    # current meaning — report them rather than collapse them silently.
    both = bind.exec_driver_sql(
        "SELECT id, code FROM promo_codes WHERE item_id IS NOT NULL AND category_id IS NOT NULL"
    ).fetchall()
    if both:
        print(
            f"WARNING: {len(both)} promo code(s) are bound to BOTH a category and an item; "
            f"scoped to 'item'. Their category binding still applies while that category "
            f"exists, but will not survive its deletion. Review: {[tuple(r) for r in both]}"
        )

    inspector = inspect(bind)
    if not _has_check(inspector, 'promo_codes', 'ck_promo_codes_scope'):
        op.create_check_constraint(
            'ck_promo_codes_scope', 'promo_codes',
            "scope IN ('global','category','item')",
        )


def downgrade() -> None:
    """Drop the discriminator.

    Lossless for every non-dangling row: scope is derivable from the FK columns.
    A promo whose target was already deleted goes back to looking unscoped —
    which is the bug this revision exists to fix.
    """
    bind = op.get_bind()
    inspector = inspect(bind)

    if 'promo_codes' not in inspector.get_table_names():
        return

    if _has_check(inspector, 'promo_codes', 'ck_promo_codes_scope'):
        op.drop_constraint('ck_promo_codes_scope', 'promo_codes', type_='check')
    if 'scope' in {c['name'] for c in inspector.get_columns('promo_codes')}:
        op.drop_column('promo_codes', 'scope')
