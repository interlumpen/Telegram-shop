"""split coarse permissions into granular bits

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-03-15 16:24:34.354124

SHOP_MANAGE (16) -> CATALOG_MANAGE (16) + STATS_VIEW (128) + PROMO_MANAGE (512)
USERS_MANAGE (8) -> USERS_MANAGE (8) + BALANCE_MANAGE (256)

Existing roles that had the old permission automatically receive the new sub-permissions.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Expand old SHOP_MANAGE (bit 4 = 16) into STATS_VIEW (128) + PROMO_MANAGE (512)
    # Expand old USERS_MANAGE (bit 3 = 8) into BALANCE_MANAGE (256)
    # Additive only: no bits are removed, no access is lost.
    op.execute(
        """
        UPDATE roles SET permissions = permissions
            | (CASE WHEN permissions & 8  != 0 THEN 256 ELSE 0 END)
            | (CASE WHEN permissions & 16 != 0 THEN 128 ELSE 0 END)
            | (CASE WHEN permissions & 16 != 0 THEN 512 ELSE 0 END)
        """
    )


def downgrade() -> None:
    # Strip the three new bits (128, 256, 512) — mask to lower 7 bits only.
    op.execute("UPDATE roles SET permissions = permissions & 127")
