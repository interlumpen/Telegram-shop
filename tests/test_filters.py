from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.database.models.main import Permission
from bot.filters.main import ValidAmountFilter, HasPermissionFilter


class TestValidAmountFilter:

    def setup_method(self):
        self.filter = ValidAmountFilter(min_amount=10, max_amount=10000)

    @pytest.mark.parametrize("text,expected", [
        ("500", True),
        ("10", True),      # exact minimum
        ("10000", True),   # exact maximum
        ("9", False),      # below minimum
        ("10001", False),  # above maximum
        ("abc", False),
        ("", False),
        (None, False),
        ("-100", False),
        ("100.5", False),  # whole units only
    ])
    async def test_amount_acceptance(self, text, expected):
        msg = MagicMock()
        msg.text = text
        assert await self.filter(msg) is expected


class TestHasPermissionFilter:

    ALL_PERMS = (
        Permission.USE | Permission.BROADCAST | Permission.SETTINGS_MANAGE
        | Permission.USERS_MANAGE | Permission.CATALOG_MANAGE | Permission.ADMINS_MANAGE
        | Permission.OWN | Permission.STATS_VIEW | Permission.BALANCE_MANAGE
        | Permission.PROMO_MANAGE
    )

    @pytest.mark.parametrize("required,granted,expected", [
        (Permission.USE, Permission.USE, True),
        (Permission.ADMINS_MANAGE, Permission.USE, False),
        (Permission.CATALOG_MANAGE,
         Permission.USE | Permission.CATALOG_MANAGE | Permission.BROADCAST, True),
        (Permission.USE, None, False),  # no role at all
        (Permission.OWN, ALL_PERMS, True),
    ])
    async def test_permission_check(self, required, granted, expected):
        f = HasPermissionFilter(permission=required)

        event = MagicMock()
        event.from_user.id = 111001

        with patch('bot.filters.main.check_role_cached',
                   new_callable=AsyncMock, return_value=granted):
            assert await f(event) is expected
