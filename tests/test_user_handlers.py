import pytest
from unittest.mock import patch
from aiogram.enums.chat_type import ChatType

from bot.database.methods.read import check_user, select_max_role_id


class TestStartHandler:

    async def test_start_creates_new_user(self, make_message, fsm_context):
        from bot.handlers.user.main import start

        msg = make_message(text="/start", user_id=300001)
        msg.chat.type = ChatType.PRIVATE

        with patch('bot.handlers.user.main.EnvKeys') as env:
            env.OWNER_ID = 999999
            env.CHANNEL_URL = ""
            env.HELPER_ID = ""
            env.RULES = ""
            await start(msg, fsm_context)

        user = await check_user(300001)
        assert user is not None
        assert user['telegram_id'] == 300001

    async def test_start_with_referral(self, make_message, fsm_context, user_factory):
        from bot.handlers.user.main import start

        # Create referrer first
        await user_factory(telegram_id=300010)

        msg = make_message(text="/start 300010", user_id=300011)
        msg.chat.type = ChatType.PRIVATE

        with patch('bot.handlers.user.main.EnvKeys') as env:
            env.OWNER_ID = 999999
            env.CHANNEL_URL = ""
            env.HELPER_ID = ""
            env.RULES = ""
            await start(msg, fsm_context)

        user = await check_user(300011)
        assert user is not None
        assert user['referral_id'] == 300010

    async def test_start_self_referral_ignored(self, make_message, fsm_context):
        from bot.handlers.user.main import start

        msg = make_message(text="/start 300020", user_id=300020)
        msg.chat.type = ChatType.PRIVATE

        with patch('bot.handlers.user.main.EnvKeys') as env:
            env.OWNER_ID = 999999
            env.CHANNEL_URL = ""
            env.HELPER_ID = ""
            env.RULES = ""
            await start(msg, fsm_context)

        user = await check_user(300020)
        assert user is not None
        assert user['referral_id'] is None

    async def test_start_owner_gets_max_role(self, make_message, fsm_context):
        from bot.handlers.user.main import start

        msg = make_message(text="/start", user_id=300030)
        msg.chat.type = ChatType.PRIVATE

        max_role = await select_max_role_id()
        with patch('bot.handlers.user.main.EnvKeys') as env:
            env.OWNER_ID = 300030
            env.CHANNEL_URL = ""
            env.HELPER_ID = ""
            env.RULES = ""
            await start(msg, fsm_context)

        user = await check_user(300030)
        assert user['role_id'] == max_role

    async def test_start_non_private_ignored(self, make_message, fsm_context):
        from bot.handlers.user.main import start

        msg = make_message(text="/start", user_id=300040)
        msg.chat.type = ChatType.GROUP

        with patch('bot.handlers.user.main.EnvKeys') as env:
            env.OWNER_ID = 999999
            await start(msg, fsm_context)

        # User should NOT be created
        user = await check_user(300040)
        assert user is None


class TestProfileHandler:

    async def test_profile_shows_balance(self, make_callback_query, fsm_context, user_factory):
        from bot.handlers.user.main import profile_callback_handler

        await user_factory(telegram_id=300050, balance=500)

        call = make_callback_query(data="profile", user_id=300050)

        with patch('bot.handlers.user.main.EnvKeys') as env:
            env.PAY_CURRENCY = "RUB"
            env.REFERRAL_PERCENT = 0
            await profile_callback_handler(call, fsm_context)

        call.message.edit_text.assert_called_once()
        text = call.message.edit_text.call_args[0][0]
        assert "500" in str(text)


class TestRulesHandler:

    async def test_rules_with_text(self, make_callback_query, fsm_context):
        from bot.handlers.user.main import rules_callback_handler

        call = make_callback_query(data="rules", user_id=300060)

        with patch('bot.handlers.user.main.EnvKeys') as env:
            env.RULES = "Shop rules text here"
            await rules_callback_handler(call, fsm_context)

        call.message.edit_text.assert_called_once()
        text = call.message.edit_text.call_args[0][0]
        assert "Shop rules text here" in text

    async def test_rules_not_set(self, make_callback_query, fsm_context):
        from bot.handlers.user.main import rules_callback_handler

        call = make_callback_query(data="rules", user_id=300070)

        with patch('bot.handlers.user.main.EnvKeys') as env:
            env.RULES = ""
            await rules_callback_handler(call, fsm_context)

        call.answer.assert_called_once()


class TestMainMenuReceivesPermissionBitmask:
    async def test_custom_role_without_admin_perms_gets_no_admin_button(
        self, make_callback_query, fsm_context, user_factory, role_factory
    ):
        from bot.handlers.user.main import back_to_menu_callback_handler
        from bot.database.models import Permission

        # A plain-user role whose *id* is >= 4, so role_id and bitmask diverge.
        role_id = await role_factory(name="PLAINCUSTOM", permissions=Permission.USE)
        assert role_id >= 4, "fixture assumption: custom roles get ids past the built-ins"

        await user_factory(telegram_id=630001, role_id=role_id)

        call = make_callback_query(data="back_to_menu", user_id=630001)
        await back_to_menu_callback_handler(call, fsm_context)

        markup = call.message.edit_text.call_args[1]["reply_markup"]
        cbs = [b.callback_data for row in markup.inline_keyboard for b in row]
        assert "console" not in cbs

    async def test_role_with_admin_perms_still_gets_the_button(
        self, make_callback_query, fsm_context, user_factory, role_factory
    ):
        from bot.handlers.user.main import back_to_menu_callback_handler
        from bot.database.models import Permission

        role_id = await role_factory(
            name="REALADMIN", permissions=Permission.USE | Permission.CATALOG_MANAGE
        )
        await user_factory(telegram_id=630002, role_id=role_id)

        call = make_callback_query(data="back_to_menu", user_id=630002)
        await back_to_menu_callback_handler(call, fsm_context)

        markup = call.message.edit_text.call_args[1]["reply_markup"]
        cbs = [b.callback_data for row in markup.inline_keyboard for b in row]
        assert "console" in cbs


class TestProfileWithoutUserRow:
    """A stale keyboard (or a wiped database) can deliver a callback from
    someone with no row; reading user fields off None used to raise."""

    async def test_profile_registers_the_missing_user(self, make_callback_query, fsm_context):
        from bot.handlers.user.main import profile_callback_handler
        from bot.database.methods.read import check_user

        assert await check_user(630010) is None

        call = make_callback_query(data="profile", user_id=630010)
        await profile_callback_handler(call, fsm_context)

        assert await check_user(630010) is not None
        call.message.edit_text.assert_called_once()
