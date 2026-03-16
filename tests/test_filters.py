import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestValidAmountFilter:

    def setup_method(self):
        from bot.filters.main import ValidAmountFilter
        self.filter = ValidAmountFilter(min_amount=10, max_amount=10000)

    @pytest.mark.asyncio
    async def test_valid_amount(self):
        msg = MagicMock()
        msg.text = "500"
        assert await self.filter(msg) is True

    @pytest.mark.asyncio
    async def test_exact_min_boundary(self):
        msg = MagicMock()
        msg.text = "10"
        assert await self.filter(msg) is True

    @pytest.mark.asyncio
    async def test_exact_max_boundary(self):
        msg = MagicMock()
        msg.text = "10000"
        assert await self.filter(msg) is True

    @pytest.mark.asyncio
    async def test_below_min(self):
        msg = MagicMock()
        msg.text = "9"
        assert await self.filter(msg) is False

    @pytest.mark.asyncio
    async def test_above_max(self):
        msg = MagicMock()
        msg.text = "10001"
        assert await self.filter(msg) is False

    @pytest.mark.asyncio
    async def test_non_digit_input(self):
        msg = MagicMock()
        msg.text = "abc"
        assert await self.filter(msg) is False

    @pytest.mark.asyncio
    async def test_empty_text(self):
        msg = MagicMock()
        msg.text = ""
        assert await self.filter(msg) is False

    @pytest.mark.asyncio
    async def test_none_text(self):
        msg = MagicMock()
        msg.text = None
        assert await self.filter(msg) is False

    @pytest.mark.asyncio
    async def test_negative_number(self):
        msg = MagicMock()
        msg.text = "-100"
        assert await self.filter(msg) is False

    @pytest.mark.asyncio
    async def test_decimal_number(self):
        msg = MagicMock()
        msg.text = "100.5"
        assert await self.filter(msg) is False


class TestHasPermissionFilter:

    @pytest.mark.asyncio
    async def test_user_has_permission(self):
        from bot.filters.main import HasPermissionFilter
        from bot.database.models.main import Permission

        f = HasPermissionFilter(permission=Permission.USE)

        event = MagicMock()
        event.from_user.id = 111001

        with patch('bot.filters.main.check_role_cached', new_callable=AsyncMock, return_value=Permission.USE):
            result = await f(event)
        assert result is True

    @pytest.mark.asyncio
    async def test_user_lacks_permission(self):
        from bot.filters.main import HasPermissionFilter
        from bot.database.models.main import Permission

        f = HasPermissionFilter(permission=Permission.ADMINS_MANAGE)

        event = MagicMock()
        event.from_user.id = 111002

        with patch('bot.filters.main.check_role_cached', new_callable=AsyncMock, return_value=Permission.USE):
            result = await f(event)
        assert result is False

    @pytest.mark.asyncio
    async def test_user_with_multiple_permissions(self):
        from bot.filters.main import HasPermissionFilter
        from bot.database.models.main import Permission

        f = HasPermissionFilter(permission=Permission.CATALOG_MANAGE)

        event = MagicMock()
        event.from_user.id = 111003

        combined = Permission.USE | Permission.CATALOG_MANAGE | Permission.BROADCAST
        with patch('bot.filters.main.check_role_cached', new_callable=AsyncMock, return_value=combined):
            result = await f(event)
        assert result is True

    @pytest.mark.asyncio
    async def test_user_no_role(self):
        from bot.filters.main import HasPermissionFilter
        from bot.database.models.main import Permission

        f = HasPermissionFilter(permission=Permission.USE)

        event = MagicMock()
        event.from_user.id = 111004

        with patch('bot.filters.main.check_role_cached', new_callable=AsyncMock, return_value=None):
            result = await f(event)
        assert result is False

    @pytest.mark.asyncio
    async def test_owner_has_all_permissions(self):
        from bot.filters.main import HasPermissionFilter
        from bot.database.models.main import Permission

        f = HasPermissionFilter(permission=Permission.OWN)

        event = MagicMock()
        event.from_user.id = 111005

        all_perms = Permission.USE | Permission.BROADCAST | Permission.SETTINGS_MANAGE | \
                    Permission.USERS_MANAGE | Permission.CATALOG_MANAGE | Permission.ADMINS_MANAGE | \
                    Permission.OWN | Permission.STATS_VIEW | Permission.BALANCE_MANAGE | Permission.PROMO_MANAGE
        with patch('bot.filters.main.check_role_cached', new_callable=AsyncMock, return_value=all_perms):
            result = await f(event)
        assert result is True
