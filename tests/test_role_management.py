from unittest.mock import patch, AsyncMock

from bot.database.methods.read import (
    get_all_roles, get_role_by_id, get_roles_with_max_perms,
    count_users_with_role, select_max_role_id, check_user,
    get_role_id_by_name,
)
from bot.database.methods.create import create_role
from bot.database.methods.update import update_role
from bot.database.methods.delete import delete_role


class TestRoleCRUDMethods:

    async def test_create_role(self):
        role_id = await create_role("MODERATOR", 11)  # USE + BROADCAST + USERS_MANAGE
        assert role_id is not None
        role = await get_role_by_id(role_id)
        assert role['name'] == "MODERATOR"
        assert role['permissions'] == 11

    async def test_create_role_duplicate_name(self):
        await create_role("DUPROLE", 3)
        result = await create_role("DUPROLE", 5)
        assert result is None

    async def test_get_all_roles(self):
        roles = await get_all_roles()
        assert len(roles) >= 3
        names = [r['name'] for r in roles]
        assert 'USER' in names
        assert 'ADMIN' in names
        assert 'OWNER' in names
        # Ordered by permissions ascending
        perms = [r['permissions'] for r in roles]
        assert perms == sorted(perms)

    async def test_get_role_by_id(self):
        role_id = await get_role_id_by_name('USER')
        role = await get_role_by_id(role_id)
        assert role is not None
        assert role['name'] == 'USER'
        assert 'permissions' in role
        assert 'default' in role

    async def test_get_role_by_id_nonexistent(self):
        role = await get_role_by_id(99999)
        assert role is None

    async def test_get_roles_with_max_perms_user_only(self):
        roles = await get_roles_with_max_perms(1)  # Only USE permission
        assert len(roles) >= 1
        for r in roles:
            assert (r['permissions'] & ~1) == 0

    async def test_get_roles_with_max_perms_all(self):
        roles = await get_roles_with_max_perms(1023)  # All permissions
        assert len(roles) >= 3  # At least USER, ADMIN, OWNER

    async def test_get_roles_with_max_perms_includes_custom(self, role_factory):
        await role_factory("HELPER", 3)
        roles = await get_roles_with_max_perms(1023)
        names = [r['name'] for r in roles]
        assert 'HELPER' in names

    async def test_count_users_with_role_empty(self):
        role_id = await get_role_id_by_name('ADMIN')
        count = await count_users_with_role(role_id)
        assert count == 0

    async def test_count_users_with_role_with_user(self, user_factory):
        await user_factory(telegram_id=700001, role_id=1)
        user_role_id = await get_role_id_by_name('USER')
        count = await count_users_with_role(user_role_id)
        assert count == 1

    async def test_update_role(self, role_factory):
        role_id = await role_factory("TOUPDATE", 3)
        success, err = await update_role(role_id, "UPDATED", 7)
        assert success is True
        assert err is None
        role = await get_role_by_id(role_id)
        assert role['name'] == "UPDATED"
        assert role['permissions'] == 7

    async def test_update_role_duplicate_name(self, role_factory):
        await role_factory("EXISTING", 3)
        role_id = await role_factory("ANOTHER", 5)
        success, err = await update_role(role_id, "EXISTING", 5)
        assert success is False
        assert "already exists" in err

    async def test_update_role_nonexistent(self):
        success, err = await update_role(99999, "GHOST", 1)
        assert success is False
        assert "not found" in err

    async def test_delete_role_custom(self, role_factory):
        role_id = await role_factory("TODELETE", 3)
        success, err = await delete_role(role_id)
        assert success is True
        assert err is None
        assert await get_role_by_id(role_id) is None

    async def test_delete_role_builtin_user(self):
        role_id = await get_role_id_by_name('USER')
        success, err = await delete_role(role_id)
        assert success is False
        # USER is both default and built-in, either error is valid
        assert "default" in err or "built-in" in err

    async def test_delete_role_builtin_admin(self):
        role_id = await get_role_id_by_name('ADMIN')
        success, err = await delete_role(role_id)
        assert success is False
        assert "built-in" in err

    async def test_delete_role_builtin_owner(self):
        role_id = await get_role_id_by_name('OWNER')
        success, err = await delete_role(role_id)
        assert success is False
        assert "built-in" in err

    async def test_delete_role_with_users(self, user_factory, role_factory):
        role_id = await role_factory("BUSYROLE", 3)
        await user_factory(telegram_id=700002, role_id=role_id)
        success, err = await delete_role(role_id)
        assert success is False
        assert "users assigned" in err

    async def test_delete_role_default(self):
        # USER role is default
        role_id = await get_role_id_by_name('USER')
        success, err = await delete_role(role_id)
        assert success is False
        # Fails on either "default" or "built-in" check
        assert success is False

    async def test_select_max_role_id_returns_highest_perms(self):
        max_id = await select_max_role_id()
        role = await get_role_by_id(max_id)
        # Should be OWNER with highest permissions
        assert role['name'] == 'OWNER'
        all_roles = await get_all_roles()
        for r in all_roles:
            assert r['permissions'] <= role['permissions']


class TestRoleManagementHandlers:

    async def test_role_list_handler(self, make_callback_query, fsm_context):
        from bot.handlers.admin.role_management_states import role_management_handler

        call = make_callback_query(data="role_mgmt", user_id=900100)

        with patch('bot.handlers.admin.role_management_states.check_role_cached',
                   new_callable=AsyncMock, return_value=127):
            await role_management_handler(call, fsm_context)

        call.message.edit_text.assert_called_once()
        text = call.message.edit_text.call_args[0][0]
        assert "admin.roles.list_title" in text

    async def test_role_view_handler(self, make_callback_query):
        from bot.handlers.admin.role_management_states import role_view_handler

        role_id = await get_role_id_by_name('USER')
        call = make_callback_query(data=f"role_v_{role_id}", user_id=900101)

        with patch('bot.handlers.admin.role_management_states.check_role_cached',
                   new_callable=AsyncMock, return_value=127):
            await role_view_handler(call)

        call.message.edit_text.assert_called_once()
        text = call.message.edit_text.call_args[0][0]
        assert "admin.roles.detail" in text

    async def test_role_view_perm_denied(self, make_callback_query):
        from bot.handlers.admin.role_management_states import role_view_handler

        # OWNER role has perms=127, caller has perms=31 (ADMIN)
        role_id = await get_role_id_by_name('OWNER')
        call = make_callback_query(data=f"role_v_{role_id}", user_id=900102)

        with patch('bot.handlers.admin.role_management_states.check_role_cached',
                   new_callable=AsyncMock, return_value=31):
            await role_view_handler(call)

        call.answer.assert_called_once()

    async def test_role_create_name(self, make_message, fsm_context):
        from bot.handlers.admin.role_management_states import role_create_name

        msg = make_message(text="Moderator", user_id=900103)
        await fsm_context.set_state("waiting_role_name")

        with patch('bot.handlers.admin.role_management_states.check_role_cached',
                   new_callable=AsyncMock, return_value=127):
            await role_create_name(msg, fsm_context)

        msg.answer.assert_called_once()
        data = await fsm_context.get_data()
        assert data['role_name'] == 'MODERATOR'
        assert data['mode'] == 'create'

    async def test_role_create_name_too_long(self, make_message, fsm_context):
        from bot.handlers.admin.role_management_states import role_create_name

        msg = make_message(text="A" * 65, user_id=900104)
        await fsm_context.set_state("waiting_role_name")

        with patch('bot.handlers.admin.role_management_states.check_role_cached',
                   new_callable=AsyncMock, return_value=127):
            await role_create_name(msg, fsm_context)

        msg.answer.assert_called_once()
        text = msg.answer.call_args[0][0]
        assert "name_invalid" in text

    async def test_role_create_done(self, make_callback_query, fsm_context):
        from bot.handlers.admin.role_management_states import _perms_done

        call = make_callback_query(data="rp_done", user_id=900105)
        await fsm_context.update_data(
            role_name="NEWROLE", role_perms=3, caller_perms=127, mode='create'
        )

        await _perms_done(call, fsm_context)

        call.message.edit_text.assert_called_once()
        text = call.message.edit_text.call_args[0][0]
        assert "admin.roles.created" in text
        # Verify role exists in DB
        role_id = await get_role_id_by_name("NEWROLE")
        assert role_id is not None

    async def test_role_create_duplicate(self, make_callback_query, fsm_context, role_factory):
        from bot.handlers.admin.role_management_states import _perms_done

        await role_factory("EXISTING", 3)
        call = make_callback_query(data="rp_done", user_id=900106)
        await fsm_context.update_data(
            role_name="EXISTING", role_perms=5, caller_perms=127, mode='create'
        )

        await _perms_done(call, fsm_context)

        call.message.edit_text.assert_called_once()
        text = call.message.edit_text.call_args[0][0]
        assert "name_exists" in text

    async def test_role_edit_skip_name(self, make_message, fsm_context):
        from bot.handlers.admin.role_management_states import role_edit_name

        await fsm_context.update_data(
            role_id=1, role_name="ORIGINAL", role_perms=3, caller_perms=127, mode='edit'
        )
        await fsm_context.set_state("editing_role_name")
        msg = make_message(text="/skip", user_id=900107)

        await role_edit_name(msg, fsm_context)

        msg.answer.assert_called_once()
        data = await fsm_context.get_data()
        assert data['role_name'] == 'ORIGINAL'

    async def test_role_edit_done(self, make_callback_query, fsm_context, role_factory):
        from bot.handlers.admin.role_management_states import _perms_done

        role_id = await role_factory("EDITABLE", 3)
        call = make_callback_query(data="rp_done", user_id=900108)
        await fsm_context.update_data(
            role_id=role_id, role_name="EDITED", role_perms=7, caller_perms=127, mode='edit'
        )

        await _perms_done(call, fsm_context)

        call.message.edit_text.assert_called_once()
        text = call.message.edit_text.call_args[0][0]
        assert "admin.roles.updated" in text
        role = await get_role_by_id(role_id)
        assert role['name'] == 'EDITED'
        assert role['permissions'] == 7

    async def test_perms_done_escalation_denied(self, make_callback_query, fsm_context):
        from bot.handlers.admin.role_management_states import _perms_done

        call = make_callback_query(data="rp_done", user_id=900109)
        await fsm_context.update_data(
            role_name="ESCALATED", role_perms=127, caller_perms=31, mode='create'
        )

        await _perms_done(call, fsm_context)

        call.answer.assert_called_once()

    async def test_toggle_perm(self, make_callback_query, fsm_context):
        from bot.handlers.admin.role_management_states import _toggle_perm

        call = make_callback_query(data="rp_t_2", user_id=900110)  # BROADCAST=2
        await fsm_context.update_data(role_perms=1, caller_perms=127)

        await _toggle_perm(call, fsm_context)

        data = await fsm_context.get_data()
        assert data['role_perms'] == 3  # 1 XOR 2 = 3

    async def test_toggle_perm_off(self, make_callback_query, fsm_context):
        from bot.handlers.admin.role_management_states import _toggle_perm

        call = make_callback_query(data="rp_t_2", user_id=900111)
        await fsm_context.update_data(role_perms=3, caller_perms=127)

        await _toggle_perm(call, fsm_context)

        data = await fsm_context.get_data()
        assert data['role_perms'] == 1  # 3 XOR 2 = 1

    async def test_toggle_perm_denied(self, make_callback_query, fsm_context):
        from bot.handlers.admin.role_management_states import _toggle_perm

        call = make_callback_query(data="rp_t_64", user_id=900112)  # OWN=64
        await fsm_context.update_data(role_perms=0, caller_perms=31)  # No OWN perm

        await _toggle_perm(call, fsm_context)

        call.answer.assert_called_once()
        data = await fsm_context.get_data()
        assert data['role_perms'] == 0  # Unchanged

    async def test_delete_role_confirm(self, make_callback_query, role_factory):
        from bot.handlers.admin.role_management_states import role_delete_confirm

        role_id = await role_factory("DELETEME", 3)
        call = make_callback_query(data=f"role_dc_{role_id}", user_id=900113)

        with patch('bot.handlers.admin.role_management_states.check_role_cached',
                   new_callable=AsyncMock, return_value=127):
            await role_delete_confirm(call)

        call.message.edit_text.assert_called_once()
        text = call.message.edit_text.call_args[0][0]
        assert "admin.roles.deleted" in text
        assert await get_role_by_id(role_id) is None

    async def test_delete_role_perm_denied(self, make_callback_query):
        from bot.handlers.admin.role_management_states import role_delete_confirm

        # OWNER role has perms=127, caller has perms=31
        role_id = await get_role_id_by_name('OWNER')
        call = make_callback_query(data=f"role_dc_{role_id}", user_id=900114)

        with patch('bot.handlers.admin.role_management_states.check_role_cached',
                   new_callable=AsyncMock, return_value=31):
            await role_delete_confirm(call)

        call.answer.assert_called_once()

    async def test_assign_role_list(self, make_callback_query, user_factory):
        from bot.handlers.admin.role_management_states import assign_role_list

        await user_factory(telegram_id=700010, role_id=1)
        call = make_callback_query(data="asr_list_700010", user_id=900115)

        with patch('bot.handlers.admin.role_management_states.check_role_cached',
                   new_callable=AsyncMock, return_value=127):
            await assign_role_list(call)

        call.message.edit_text.assert_called_once()
        text = call.message.edit_text.call_args[0][0]
        assert "admin.roles.assign_prompt" in text

    async def test_assign_role_list_owner_protected(self, make_callback_query, user_factory):
        from bot.handlers.admin.role_management_states import assign_role_list

        max_role = await select_max_role_id()
        await user_factory(telegram_id=700011, role_id=max_role)
        call = make_callback_query(data="asr_list_700011", user_id=900116)

        with patch('bot.handlers.admin.role_management_states.check_role_cached',
                   new_callable=AsyncMock, return_value=127):
            await assign_role_list(call)

        call.answer.assert_called_once()

    async def test_assign_role_perm_denied(self, make_callback_query, user_factory):
        from bot.handlers.admin.role_management_states import assign_role_confirm

        await user_factory(telegram_id=700012, role_id=1)
        owner_role_id = await get_role_id_by_name('OWNER')
        call = make_callback_query(data=f"asr_{owner_role_id}_700012", user_id=900117)

        # Caller has ADMIN perms (31), trying to assign OWNER role (127)
        with patch('bot.handlers.admin.role_management_states.check_role_cached',
                   new_callable=AsyncMock, return_value=31):
            await assign_role_confirm(call)

        call.answer.assert_called_once()
        user = await check_user(700012)
        assert user['role_id'] == 1  # Unchanged


class TestHelpers:

    def test_format_permissions_all(self):
        from bot.handlers.admin.role_management_states import _format_permissions
        result = _format_permissions(127)
        assert "USE" in result
        assert "BROADCAST" in result
        assert "OWNER" in result

    def test_format_permissions_none(self):
        from bot.handlers.admin.role_management_states import _format_permissions
        assert _format_permissions(0) == "\u2014"  # em dash

    def test_format_permissions_partial(self):
        from bot.handlers.admin.role_management_states import _format_permissions
        result = _format_permissions(3)  # USE + BROADCAST
        assert "USE" in result
        assert "BROADCAST" in result
        assert "SHOP" not in result

    def test_build_perms_keyboard_filters_by_caller(self):
        from bot.handlers.admin.role_management_states import _build_perms_keyboard
        # Caller only has USE + BROADCAST (3)
        markup = _build_perms_keyboard(0, 3)
        texts = [btn.text for row in markup.inline_keyboard for btn in row]
        # Should only have USE and BROADCAST toggles + confirm + back
        perm_buttons = [t for t in texts if t.startswith("[")]
        assert len(perm_buttons) == 2
        assert any("USE" in t for t in perm_buttons)
        assert any("BROADCAST" in t for t in perm_buttons)

    def test_build_perms_keyboard_shows_checked(self):
        from bot.handlers.admin.role_management_states import _build_perms_keyboard
        markup = _build_perms_keyboard(1, 127)  # USE is on
        texts = [btn.text for row in markup.inline_keyboard for btn in row]
        use_btn = next(t for t in texts if "USE" in t)
        assert "\u2713" in use_btn  # checkmark


class TestPermissionHelpers:

    def test_subset_same(self):
        from bot.database.models import Permission
        assert Permission.is_subset(31, 31) is True

    def test_subset_less_bits(self):
        from bot.database.models import Permission
        assert Permission.is_subset(1, 31) is True  # USE is subset of ADMIN

    def test_subset_fails_extra_bit(self):
        from bot.database.models import Permission
        assert Permission.is_subset(32, 31) is False  # ADMINS_MANAGE not in ADMIN(31)

    def test_subset_zero(self):
        from bot.database.models import Permission
        assert Permission.is_subset(0, 0) is True

    def test_has_any_admin_perm_true(self):
        from bot.database.models import Permission
        assert Permission.has_any_admin_perm(31) is True  # ADMIN

    def test_has_any_admin_perm_false(self):
        from bot.database.models import Permission
        assert Permission.has_any_admin_perm(1) is False  # Only USE

    def test_has_any_admin_perm_zero(self):
        from bot.database.models import Permission
        assert Permission.has_any_admin_perm(0) is False


class TestBitwiseRegressions:

    async def test_get_roles_with_max_perms_bitwise_correctness(self, role_factory):
        """Role with ADMINS_MANAGE(32) should NOT appear when caller_perms=31."""
        await role_factory("ONLY_ADMIN_MANAGE", 32)
        roles = await get_roles_with_max_perms(31)
        names = [r['name'] for r in roles]
        assert "ONLY_ADMIN_MANAGE" not in names

    async def test_get_roles_with_max_perms_subset_included(self, role_factory):
        """Role with USE+BROADCAST(3) should appear when caller_perms=31."""
        await role_factory("HELPER_ROLE", 3)
        roles = await get_roles_with_max_perms(31)
        names = [r['name'] for r in roles]
        assert "HELPER_ROLE" in names

    async def test_perms_done_escalation_denied_bitwise(self, make_callback_query, fsm_context):
        """perms=32 (ADMINS_MANAGE only) denied when caller=31 (ADMIN)."""
        from bot.handlers.admin.role_management_states import _perms_done

        call = make_callback_query(data="rp_done", user_id=900120)
        await fsm_context.update_data(
            role_name="ESCALATED2", role_perms=32, caller_perms=31, mode='create'
        )

        await _perms_done(call, fsm_context)

        call.answer.assert_called_once()
