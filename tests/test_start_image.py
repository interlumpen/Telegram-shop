import hashlib
from importlib import import_module
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.exceptions import TelegramBadRequest
from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError

import bot.database.methods.audit as audit_module
from bot.database.main import Database
from bot.database.methods.read import check_user, get_start_image_file_id
from bot.database.methods.update import set_start_image_file_id
from bot.database.models.main import AuditLog, Permission, StorefrontSettings
from bot.filters import HasPermissionFilter
from bot.handlers.admin import main as admin_main_handlers
from bot.handlers.admin import start_image_settings as settings_handlers
from bot.handlers.other import transition_to_text
from bot.handlers.user import main as user_handlers
from bot.handlers.user import shop_and_goods as shop_handlers
from bot.i18n import localize
from bot.keyboards import main_menu, start_image_settings_keyboard
from bot.states import ShopStates, StorefrontSettingsFSM

update_module = import_module("bot.database.methods.update")


SETTINGS_ROLE = Permission.USE | Permission.SETTINGS_MANAGE
FEATURE_AUDIT_ACTIONS = (
    "start_image_added",
    "start_image_replaced",
    "start_image_removed",
)


def _callback_data(markup) -> set[str]:
    return {
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
        if button.callback_data
    }


def _bad_request(message: str) -> TelegramBadRequest:
    return TelegramBadRequest(method=MagicMock(), message=message)


def _as_photo_callback(call):
    """Make a callback originate from the photo-with-caption /start message."""
    call.message.text = None
    call.message.caption = "menu.title"
    call.message.photo = [MagicMock(file_id="fake-large-photo-id")]
    call.message.reply_markup = MagicMock()
    call.message.delete = AsyncMock()
    call.message.answer = AsyncMock()
    call.message.answer_photo = AsyncMock()
    return call


@pytest.fixture
async def storefront_row():
    """Seed the singleton row normally created by the Alembic migration."""
    async with Database().session() as session:
        await session.execute(delete(StorefrontSettings))
        await session.execute(
            delete(AuditLog).where(AuditLog.action.in_(FEATURE_AUDIT_ACTIONS))
        )
        session.add(StorefrontSettings(id=1, start_image_file_id=None))

    yield

    async with Database().session() as session:
        await session.execute(delete(StorefrontSettings))
        await session.execute(
            delete(AuditLog).where(AuditLog.action.in_(FEATURE_AUDIT_ACTIONS))
        )


class TestStartScreenRenderer:
    async def test_without_image_preserves_text_and_role_aware_keyboard(self, make_message):
        message = make_message()
        message.answer_photo = AsyncMock()

        with patch.object(
            user_handlers, "get_start_image_file_id", new_callable=AsyncMock, return_value=None
        ), patch.object(user_handlers, "_parse_channel_username", return_value=None), patch.object(
            user_handlers.EnvKeys, "HELPER_ID", ""
        ):
            await user_handlers.render_start_screen(message, SETTINGS_ROLE)

        message.answer.assert_awaited_once()
        assert message.answer.await_args.args[0] == "menu.title"
        assert {"shop", "rules", "profile", "console"}.issubset(
            _callback_data(message.answer.await_args.kwargs["reply_markup"])
        )
        message.answer_photo.assert_not_awaited()

    async def test_configured_image_uses_original_text_and_keyboard(self, make_message):
        message = make_message()
        message.answer_photo = AsyncMock()

        with patch.object(
            user_handlers,
            "get_start_image_file_id",
            new_callable=AsyncMock,
            return_value="fake-large-photo-id",
        ), patch.object(user_handlers, "_parse_channel_username", return_value=None), patch.object(
            user_handlers.EnvKeys, "HELPER_ID", ""
        ):
            await user_handlers.render_start_screen(message, SETTINGS_ROLE)

        message.answer_photo.assert_awaited_once()
        kwargs = message.answer_photo.await_args.kwargs
        assert kwargs["photo"] == "fake-large-photo-id"
        assert kwargs["caption"] == "menu.title"
        assert {"shop", "rules", "profile", "console"}.issubset(
            _callback_data(kwargs["reply_markup"])
        )
        message.answer.assert_not_awaited()

    async def test_long_text_is_not_truncated(self, make_message):
        message = make_message()
        message.answer_photo = AsyncMock()
        long_text = "x" * 1025

        with patch.object(
            user_handlers,
            "get_start_image_file_id",
            new_callable=AsyncMock,
            return_value="fake-large-photo-id",
        ), patch.object(user_handlers, "localize", return_value=long_text), patch.object(
            user_handlers, "_parse_channel_username", return_value=None
        ), patch.object(user_handlers.EnvKeys, "HELPER_ID", ""):
            await user_handlers.render_start_screen(message, SETTINGS_ROLE)

        message.answer_photo.assert_awaited_once_with(photo="fake-large-photo-id")
        message.answer.assert_awaited_once()
        assert message.answer.await_args.args[0] == long_text
        assert len(message.answer.await_args.args[0]) == 1025
        assert "console" in _callback_data(message.answer.await_args.kwargs["reply_markup"])

    async def test_unavailable_file_id_falls_back_without_logging_it(self, make_message):
        message = make_message()
        message.answer_photo = AsyncMock(side_effect=_bad_request(
            "Bad Request: wrong file identifier/http url specified"
        ))

        with patch.object(
            user_handlers,
            "get_start_image_file_id",
            new_callable=AsyncMock,
            return_value="fake-unavailable-photo-id",
        ), patch.object(user_handlers, "_parse_channel_username", return_value=None), patch.object(
            user_handlers.EnvKeys, "HELPER_ID", ""
        ), patch.object(user_handlers.logger, "warning") as warning:
            await user_handlers.render_start_screen(message, SETTINGS_ROLE)

        message.answer.assert_awaited_once()
        assert message.answer.await_args.args[0] == "menu.title"
        assert "console" in _callback_data(message.answer.await_args.kwargs["reply_markup"])
        warning.assert_called_once_with("start_screen_image_unusable")
        assert "fake-unavailable-photo-id" not in repr(warning.call_args_list)

    async def test_unrelated_telegram_error_propagates(self, make_message):
        message = make_message()
        message.answer_photo = AsyncMock(side_effect=_bad_request("Bad Request: chat not found"))

        with patch.object(
            user_handlers,
            "get_start_image_file_id",
            new_callable=AsyncMock,
            return_value="fake-large-photo-id",
        ), patch.object(user_handlers, "_parse_channel_username", return_value=None), patch.object(
            user_handlers.EnvKeys, "HELPER_ID", ""
        ), pytest.raises(TelegramBadRequest, match="chat not found"):
            await user_handlers.render_start_screen(message, SETTINGS_ROLE)

        message.answer.assert_not_awaited()

    async def test_real_start_flow_uses_shared_renderer(self, make_message, fsm_context):
        message = make_message(text="/start", user_id=710001)

        with patch.object(
            user_handlers, "check_role_cached", new_callable=AsyncMock, return_value=SETTINGS_ROLE
        ), patch.object(user_handlers, "_parse_channel_username", return_value=None), patch.object(
            user_handlers, "render_start_screen", new_callable=AsyncMock
        ) as renderer:
            await user_handlers.start(message, fsm_context)

        renderer.assert_awaited_once_with(message, SETTINGS_ROLE)

    async def test_preview_calls_shared_renderer_with_admin_role(self, make_callback_query):
        call = make_callback_query(data="start_image_preview", user_id=710002)

        with patch.object(
            settings_handlers,
            "check_role_cached",
            new_callable=AsyncMock,
            return_value=SETTINGS_ROLE,
        ), patch.object(
            settings_handlers, "render_start_screen", new_callable=AsyncMock
        ) as renderer:
            await settings_handlers.start_image_preview_handler(call)

        call.message.answer.assert_awaited_once_with(localize("admin.start_image.preview_label"))
        renderer.assert_awaited_once_with(call.message, SETTINGS_ROLE)


class TestPhotoStartNavigation:
    async def test_console_from_photo_replaces_media_with_text(
        self, make_callback_query, fsm_context
    ):
        call = _as_photo_callback(
            make_callback_query(data="console", user_id=715001)
        )

        with patch.object(
            admin_main_handlers,
            "check_role_cached",
            new_callable=AsyncMock,
            return_value=SETTINGS_ROLE,
        ), patch.object(admin_main_handlers, "get_auth_middleware", return_value=None):
            await admin_main_handlers.console_callback_handler(call, fsm_context)

        call.message.edit_text.assert_not_awaited()
        call.message.delete.assert_awaited_once()
        call.message.answer.assert_awaited_once()
        assert call.message.answer.await_args.args[0] == localize("admin.menu.main")

    async def test_shop_from_photo_replaces_media_with_text(
        self, make_callback_query, fsm_context
    ):
        call = _as_photo_callback(make_callback_query(data="shop", user_id=715002))

        with patch.object(shop_handlers, "get_metrics", return_value=None), patch.object(
            shop_handlers,
            "lazy_paginated_keyboard",
            new_callable=AsyncMock,
            return_value=MagicMock(),
        ):
            await shop_handlers.shop_callback_handler(call, fsm_context)

        call.message.edit_text.assert_not_awaited()
        call.message.delete.assert_awaited_once()
        call.message.answer.assert_awaited_once()
        assert await fsm_context.get_state() == ShopStates.viewing_categories

    async def test_profile_from_photo_replaces_media_with_text(
        self, make_callback_query, fsm_context, user_factory
    ):
        await user_factory(telegram_id=715003, balance=25)
        call = _as_photo_callback(make_callback_query(data="profile", user_id=715003))

        with patch.object(user_handlers.EnvKeys, "PAY_CURRENCY", "RUB"), patch.object(
            user_handlers.EnvKeys, "REFERRAL_PERCENT", 0
        ):
            await user_handlers.profile_callback_handler(call, fsm_context)

        call.message.edit_text.assert_not_awaited()
        call.message.delete.assert_awaited_once()
        call.message.answer.assert_awaited_once()
        assert "25" in call.message.answer.await_args.args[0]

    async def test_rules_from_photo_replaces_media_with_text(
        self, make_callback_query, fsm_context
    ):
        call = _as_photo_callback(make_callback_query(data="rules", user_id=715004))

        with patch.object(user_handlers.EnvKeys, "RULES", "Local rules"):
            await user_handlers.rules_callback_handler(call, fsm_context)

        call.message.edit_text.assert_not_awaited()
        call.message.delete.assert_awaited_once()
        call.message.answer.assert_awaited_once_with(
            "Local rules",
            reply_markup=call.message.answer.await_args.kwargs["reply_markup"],
        )

    def test_all_main_menu_callbacks_use_covered_entry_paths(self):
        callbacks = _callback_data(main_menu(role=SETTINGS_ROLE))
        assert callbacks == {"shop", "rules", "profile", "console"}

    async def test_text_source_still_edits_in_place(self, make_callback_query):
        call = make_callback_query(data="rules", user_id=715005)
        call.message.text = "menu.title"
        call.message.delete = AsyncMock()
        call.message.answer = AsyncMock()

        await transition_to_text(call.message, "Destination", reply_markup=MagicMock())

        call.message.edit_text.assert_awaited_once()
        call.message.delete.assert_not_awaited()
        call.message.answer.assert_not_awaited()

    async def test_expected_delete_failure_falls_back_to_new_text(
        self, make_callback_query
    ):
        call = _as_photo_callback(make_callback_query(user_id=715006))
        call.message.delete.side_effect = _bad_request(
            "Bad Request: message can't be deleted"
        )

        await transition_to_text(call.message, "Destination")

        call.message.answer.assert_awaited_once_with("Destination")

    async def test_unrelated_delete_error_propagates(self, make_callback_query):
        call = _as_photo_callback(make_callback_query(user_id=715007))
        call.message.delete.side_effect = _bad_request("Bad Request: chat not found")

        with pytest.raises(TelegramBadRequest, match="chat not found"):
            await transition_to_text(call.message, "Destination")

        call.message.answer.assert_not_awaited()

    async def test_back_to_menu_restores_configured_photo_and_preserves_setting(
        self, storefront_row, make_callback_query, fsm_context, caplog
    ):
        await set_start_image_file_id("fake-large-photo-id", 715008)
        call = make_callback_query(data="back_to_menu", user_id=715008)
        call.message.text = "profile.caption"
        call.message.delete = AsyncMock()
        call.message.answer = AsyncMock()
        call.message.answer_photo = AsyncMock()

        with patch.object(
            user_handlers, "_ensure_user", new_callable=AsyncMock, return_value={}
        ), patch.object(
            user_handlers,
            "check_role_cached",
            new_callable=AsyncMock,
            return_value=SETTINGS_ROLE,
        ), patch.object(user_handlers, "_parse_channel_username", return_value=None), patch.object(
            user_handlers.EnvKeys, "HELPER_ID", ""
        ), caplog.at_level("WARNING", logger="bot"):
            await user_handlers.back_to_menu_callback_handler(call, fsm_context)

        call.message.edit_text.assert_not_awaited()
        call.message.delete.assert_awaited_once()
        call.message.answer_photo.assert_awaited_once()
        assert call.message.answer_photo.await_args.kwargs["caption"] == "menu.title"
        assert await get_start_image_file_id() == "fake-large-photo-id"
        assert "fake-large-photo-id" not in caplog.text

    async def test_back_to_menu_without_image_edits_existing_text(
        self, storefront_row, make_callback_query, fsm_context
    ):
        call = make_callback_query(data="back_to_menu", user_id=715009)
        call.message.text = "profile.caption"
        call.message.delete = AsyncMock()
        call.message.answer = AsyncMock()
        call.message.answer_photo = AsyncMock()

        with patch.object(
            user_handlers, "_ensure_user", new_callable=AsyncMock, return_value={}
        ), patch.object(
            user_handlers,
            "check_role_cached",
            new_callable=AsyncMock,
            return_value=SETTINGS_ROLE,
        ), patch.object(user_handlers, "_parse_channel_username", return_value=None), patch.object(
            user_handlers.EnvKeys, "HELPER_ID", ""
        ):
            await user_handlers.back_to_menu_callback_handler(call, fsm_context)

        call.message.edit_text.assert_awaited_once()
        assert call.message.edit_text.await_args.args[0] == "menu.title"
        call.message.delete.assert_not_awaited()
        call.message.answer.assert_not_awaited()
        call.message.answer_photo.assert_not_awaited()


class TestStartImageAdminFlow:
    @pytest.mark.parametrize("configured", [False, True])
    async def test_settings_card_reports_state(
        self, configured, make_callback_query, fsm_context
    ):
        call = make_callback_query(data="start_image_settings", user_id=720001)
        stored = "fake-large-photo-id" if configured else None

        with patch.object(
            settings_handlers,
            "check_role_cached",
            new_callable=AsyncMock,
            return_value=SETTINGS_ROLE,
        ), patch.object(
            settings_handlers,
            "get_start_image_file_id",
            new_callable=AsyncMock,
            return_value=stored,
        ):
            await settings_handlers.start_image_settings_handler(call, fsm_context)

        expected_status = localize(
            "admin.start_image.status_configured" if configured
            else "admin.start_image.status_empty"
        )
        assert expected_status in call.message.edit_text.await_args.args[0]
        callbacks = _callback_data(call.message.edit_text.await_args.kwargs["reply_markup"])
        labels = {
            button.text
            for row in call.message.edit_text.await_args.kwargs["reply_markup"].inline_keyboard
            for button in row
        }
        assert ("start_image_remove" in callbacks) is configured
        assert "start_image_upload" in callbacks
        assert "start_image_preview" in callbacks
        expected_action = localize(
            "admin.start_image.replace" if configured else "admin.start_image.add"
        )
        assert expected_action in labels

    @pytest.mark.parametrize("configured", [False, True], ids=["add", "replace"])
    async def test_add_and_replace_enter_upload_state(
        self, configured, make_callback_query, fsm_context
    ):
        assert "start_image_upload" in _callback_data(start_image_settings_keyboard(configured))
        call = make_callback_query(data="start_image_upload", user_id=720002)

        with patch.object(
            settings_handlers,
            "check_role_cached",
            new_callable=AsyncMock,
            return_value=SETTINGS_ROLE,
        ):
            await settings_handlers.start_image_upload_handler(call, fsm_context)

        assert await fsm_context.get_state() == StorefrontSettingsFSM.waiting_start_image

    @pytest.mark.parametrize(
        ("previously_configured", "notice_key"),
        [
            (False, "admin.start_image.added"),
            (True, "admin.start_image.replaced"),
        ],
        ids=["add", "replace"],
    )
    async def test_photo_uses_largest_size_and_clears_only_after_persistence(
        self, previously_configured, notice_key, make_message, fsm_context
    ):
        message = make_message(user_id=720003)
        message.photo = [
            MagicMock(file_id="fake-small-photo-id"),
            MagicMock(file_id="fake-large-photo-id"),
        ]
        await fsm_context.set_state(StorefrontSettingsFSM.waiting_start_image)

        async def persist(file_id, admin_id):
            assert file_id == "fake-large-photo-id"
            assert admin_id == 720003
            assert await fsm_context.get_state() == StorefrontSettingsFSM.waiting_start_image
            return previously_configured

        with patch.object(
            settings_handlers,
            "check_role_cached",
            new_callable=AsyncMock,
            return_value=SETTINGS_ROLE,
        ), patch.object(
            settings_handlers,
            "set_start_image_file_id",
            new_callable=AsyncMock,
            side_effect=persist,
        ) as setter:
            await settings_handlers.save_start_image_handler(message, fsm_context)

        setter.assert_awaited_once_with("fake-large-photo-id", 720003)
        assert await fsm_context.get_state() is None
        assert localize(notice_key) in message.answer.await_args.args[0]
        callbacks = _callback_data(message.answer.await_args.kwargs["reply_markup"])
        assert {"start_image_upload", "start_image_remove", "start_image_preview"}.issubset(callbacks)
        assert "fake-large-photo-id" not in str(message.answer.await_args_list)

    @pytest.mark.parametrize(
        "unsupported", ["text", "document", "video", "animation", "sticker"]
    )
    async def test_unsupported_input_is_rejected_and_state_remains(
        self, unsupported, make_message, fsm_context
    ):
        message = make_message(text="not a photo", user_id=720004)
        setattr(message, unsupported, MagicMock())
        await fsm_context.set_state(StorefrontSettingsFSM.waiting_start_image)

        with patch.object(
            settings_handlers,
            "check_role_cached",
            new_callable=AsyncMock,
            return_value=SETTINGS_ROLE,
        ):
            await settings_handlers.reject_non_photo_handler(message)

        assert await fsm_context.get_state() == StorefrontSettingsFSM.waiting_start_image
        assert localize("admin.start_image.photo_required") in message.answer.await_args.args[0]

    async def test_cancellation_preserves_existing_image(
        self, make_callback_query, fsm_context
    ):
        call = make_callback_query(data="start_image_settings", user_id=720005)
        await fsm_context.set_state(StorefrontSettingsFSM.waiting_start_image)

        with patch.object(
            settings_handlers,
            "check_role_cached",
            new_callable=AsyncMock,
            return_value=SETTINGS_ROLE,
        ), patch.object(
            settings_handlers,
            "get_start_image_file_id",
            new_callable=AsyncMock,
            return_value="fake-large-photo-id",
        ), patch.object(
            settings_handlers, "set_start_image_file_id", new_callable=AsyncMock
        ) as setter:
            await settings_handlers.start_image_settings_handler(call, fsm_context)

        setter.assert_not_awaited()
        assert await fsm_context.get_state() is None

    async def test_persistence_failure_keeps_state_and_has_no_success_response(
        self, make_message, fsm_context, caplog
    ):
        message = make_message(user_id=720006)
        message.photo = [MagicMock(file_id="fake-large-photo-id")]
        await fsm_context.set_state(StorefrontSettingsFSM.waiting_start_image)

        with patch.object(
            settings_handlers,
            "check_role_cached",
            new_callable=AsyncMock,
            return_value=SETTINGS_ROLE,
        ), patch.object(
            settings_handlers,
            "set_start_image_file_id",
            new_callable=AsyncMock,
            side_effect=SQLAlchemyError("database unavailable"),
        ), caplog.at_level("ERROR", logger="bot"):
            await settings_handlers.save_start_image_handler(message, fsm_context)

        assert await fsm_context.get_state() == StorefrontSettingsFSM.waiting_start_image
        assert message.answer.await_count == 1
        response = message.answer.await_args.args[0]
        assert localize("admin.start_image.save_failed") == response
        assert localize("admin.start_image.added") not in response
        assert localize("admin.start_image.replaced") not in response
        assert "fake-large-photo-id" not in caplog.text

    async def test_removal_requires_confirmation(self, make_callback_query, fsm_context):
        call = make_callback_query(data="start_image_remove", user_id=720007)

        with patch.object(
            settings_handlers,
            "check_role_cached",
            new_callable=AsyncMock,
            return_value=SETTINGS_ROLE,
        ), patch.object(
            settings_handlers,
            "get_start_image_file_id",
            new_callable=AsyncMock,
            return_value="fake-large-photo-id",
        ), patch.object(
            settings_handlers, "set_start_image_file_id", new_callable=AsyncMock
        ) as setter:
            await settings_handlers.start_image_remove_handler(call, fsm_context)

        setter.assert_not_awaited()
        assert await fsm_context.get_state() == StorefrontSettingsFSM.confirming_start_image_removal
        callbacks = _callback_data(call.message.edit_text.await_args.kwargs["reply_markup"])
        assert "start_image_remove_confirm" in callbacks

    async def test_removal_is_safe_when_already_empty(self, make_callback_query, fsm_context):
        call = make_callback_query(data="start_image_remove", user_id=720008)

        with patch.object(
            settings_handlers,
            "check_role_cached",
            new_callable=AsyncMock,
            return_value=SETTINGS_ROLE,
        ), patch.object(
            settings_handlers,
            "get_start_image_file_id",
            new_callable=AsyncMock,
            return_value=None,
        ), patch.object(
            settings_handlers, "set_start_image_file_id", new_callable=AsyncMock
        ) as setter:
            await settings_handlers.start_image_remove_handler(call, fsm_context)

        setter.assert_not_awaited()
        assert await fsm_context.get_state() is None
        assert localize("admin.start_image.already_empty") in call.message.edit_text.await_args.args[0]

    async def test_stale_confirmation_does_not_report_removal(
        self, make_callback_query, fsm_context
    ):
        call = make_callback_query(data="start_image_remove_confirm", user_id=720009)
        await fsm_context.set_state(StorefrontSettingsFSM.confirming_start_image_removal)
        await fsm_context.update_data(start_image_fingerprint="stale-fingerprint")

        with patch.object(
            settings_handlers,
            "check_role_cached",
            new_callable=AsyncMock,
            return_value=SETTINGS_ROLE,
        ), patch.object(
            settings_handlers,
            "set_start_image_file_id",
            new_callable=AsyncMock,
            return_value=None,
        ), patch.object(
            settings_handlers,
            "get_start_image_file_id",
            new_callable=AsyncMock,
            return_value="fake-large-photo-id",
        ):
            await settings_handlers.start_image_remove_confirm_handler(call, fsm_context)

        assert await fsm_context.get_state() is None
        assert localize("admin.start_image.stale") in call.answer.await_args.args[0]
        assert localize("admin.start_image.removed") not in call.message.edit_text.await_args.args[0]

    async def test_confirmed_removal_clears_state_and_returns_card(
        self, make_callback_query, fsm_context
    ):
        call = make_callback_query(data="start_image_remove_confirm", user_id=720010)
        fingerprint = hashlib.sha256(b"fake-large-photo-id").hexdigest()
        await fsm_context.set_state(StorefrontSettingsFSM.confirming_start_image_removal)
        await fsm_context.update_data(start_image_fingerprint=fingerprint)

        with patch.object(
            settings_handlers,
            "check_role_cached",
            new_callable=AsyncMock,
            return_value=SETTINGS_ROLE,
        ), patch.object(
            settings_handlers,
            "set_start_image_file_id",
            new_callable=AsyncMock,
            return_value=True,
        ) as setter:
            await settings_handlers.start_image_remove_confirm_handler(call, fsm_context)

        setter.assert_awaited_once_with(
            None,
            720010,
            expected_file_id_fingerprint=fingerprint,
        )
        assert await fsm_context.get_state() is None
        assert localize("admin.start_image.removed") in call.message.edit_text.await_args.args[0]
        callbacks = _callback_data(call.message.edit_text.await_args.kwargs["reply_markup"])
        assert "start_image_remove" not in callbacks


class TestStartImageAuthorization:
    def test_every_feature_handler_keeps_registered_permission_filter(self):
        callbacks = (
            settings_handlers.start_image_settings_handler,
            settings_handlers.start_image_upload_handler,
            settings_handlers.start_image_remove_handler,
            settings_handlers.start_image_remove_confirm_handler,
            settings_handlers.start_image_preview_handler,
        )
        messages = (
            settings_handlers.save_start_image_handler,
            settings_handlers.reject_non_photo_handler,
        )

        registrations = [
            *settings_handlers.router.callback_query.handlers,
            *settings_handlers.router.message.handlers,
        ]
        for callback in (*callbacks, *messages):
            registration = next(item for item in registrations if item.callback is callback)
            permission_filters = [
                item.callback
                for item in registration.filters
                if isinstance(item.callback, HasPermissionFilter)
            ]
            assert len(permission_filters) == 1
            assert permission_filters[0].permission == Permission.SETTINGS_MANAGE

    async def test_direct_unauthorized_callbacks_cannot_read_or_modify_configuration(
        self, make_callback_query, fsm_context
    ):
        get_setting = AsyncMock(return_value="fake-large-photo-id")
        set_setting = AsyncMock()
        renderer = AsyncMock()

        with patch.object(
            settings_handlers,
            "check_role_cached",
            new_callable=AsyncMock,
            return_value=Permission.USE,
        ), patch.object(settings_handlers, "get_start_image_file_id", get_setting), patch.object(
            settings_handlers, "set_start_image_file_id", set_setting
        ), patch.object(settings_handlers, "render_start_screen", renderer):
            calls = [
                make_callback_query(data="start_image_settings", user_id=730001),
                make_callback_query(data="start_image_upload", user_id=730001),
                make_callback_query(data="start_image_remove", user_id=730001),
                make_callback_query(data="start_image_preview", user_id=730001),
            ]
            await settings_handlers.start_image_settings_handler(calls[0], fsm_context)
            await settings_handlers.start_image_upload_handler(calls[1], fsm_context)
            await settings_handlers.start_image_remove_handler(calls[2], fsm_context)
            await settings_handlers.start_image_preview_handler(calls[3])

            confirm_state = type(fsm_context)()
            await confirm_state.set_state(StorefrontSettingsFSM.confirming_start_image_removal)
            await confirm_state.update_data(start_image_fingerprint="stale-fingerprint")
            confirm = make_callback_query(data="start_image_remove_confirm", user_id=730001)
            await settings_handlers.start_image_remove_confirm_handler(confirm, confirm_state)

        get_setting.assert_not_awaited()
        set_setting.assert_not_awaited()
        renderer.assert_not_awaited()
        for call in [*calls, confirm]:
            call.answer.assert_awaited_once_with(localize("admin.menu.rights"), show_alert=True)

    async def test_direct_unauthorized_photo_cannot_modify_configuration(
        self, make_message, fsm_context
    ):
        message = make_message(user_id=730002)
        message.photo = [MagicMock(file_id="fake-large-photo-id")]
        await fsm_context.set_state(StorefrontSettingsFSM.waiting_start_image)

        with patch.object(
            settings_handlers,
            "check_role_cached",
            new_callable=AsyncMock,
            return_value=Permission.USE,
        ), patch.object(
            settings_handlers, "set_start_image_file_id", new_callable=AsyncMock
        ) as setter:
            await settings_handlers.save_start_image_handler(message, fsm_context)

        setter.assert_not_awaited()
        assert await fsm_context.get_state() == StorefrontSettingsFSM.waiting_start_image
        message.answer.assert_awaited_once_with(localize("admin.menu.rights"))

    async def test_missing_confirmation_data_cannot_remove_image(
        self, make_callback_query, fsm_context
    ):
        call = make_callback_query(data="start_image_remove_confirm", user_id=730003)
        await fsm_context.set_state(StorefrontSettingsFSM.confirming_start_image_removal)

        with patch.object(
            settings_handlers,
            "check_role_cached",
            new_callable=AsyncMock,
            return_value=SETTINGS_ROLE,
        ), patch.object(
            settings_handlers, "set_start_image_file_id", new_callable=AsyncMock
        ) as setter:
            await settings_handlers.start_image_remove_confirm_handler(call, fsm_context)

        setter.assert_not_awaited()
        assert await fsm_context.get_state() is None
        assert localize("admin.start_image.stale") in call.answer.await_args.args[0]


class TestStartImagePersistence:
    async def test_store_replace_and_remove_preserve_unrelated_data(
        self, storefront_row, user_factory
    ):
        await user_factory(telegram_id=740001, balance=321)

        assert await get_start_image_file_id() is None
        assert await set_start_image_file_id("fake-small-photo-id", 740010) is False
        assert await get_start_image_file_id() == "fake-small-photo-id"

        assert await set_start_image_file_id("fake-large-photo-id", 740010) is True
        assert await get_start_image_file_id() == "fake-large-photo-id"
        assert (await check_user(740001))["balance"] == 321

        fingerprint = hashlib.sha256(b"fake-large-photo-id").hexdigest()
        assert await set_start_image_file_id(
            None,
            740010,
            expected_file_id_fingerprint=fingerprint,
        ) is True
        assert await get_start_image_file_id() is None
        assert (await check_user(740001))["balance"] == 321

    async def test_stale_removal_preserves_current_value(self, storefront_row):
        await set_start_image_file_id("fake-large-photo-id", 740011)

        result = await set_start_image_file_id(
            None,
            740011,
            expected_file_id_fingerprint=hashlib.sha256(b"different-photo-id").hexdigest(),
        )

        assert result is None
        assert await get_start_image_file_id() == "fake-large-photo-id"

    async def test_transaction_failure_rolls_back_replacement(self, storefront_row):
        await set_start_image_file_id("fake-small-photo-id", 740012)

        with patch.object(
            update_module,
            "log_audit",
            new_callable=AsyncMock,
            side_effect=SQLAlchemyError("audit insert failed"),
        ), pytest.raises(SQLAlchemyError, match="audit insert failed"):
            await set_start_image_file_id("fake-large-photo-id", 740012)

        assert await get_start_image_file_id() == "fake-small-photo-id"

    async def test_audit_and_logs_contain_no_file_id(self, storefront_row):
        with patch.object(audit_module.audit_logger, "log") as audit_log:
            await set_start_image_file_id("fake-small-photo-id", 740013)
            await set_start_image_file_id("fake-large-photo-id", 740013)
            fingerprint = hashlib.sha256(b"fake-large-photo-id").hexdigest()
            await set_start_image_file_id(
                None,
                740013,
                expected_file_id_fingerprint=fingerprint,
            )

        async with Database().session() as session:
            rows = (await session.execute(
                select(AuditLog)
                .where(AuditLog.action.in_(FEATURE_AUDIT_ACTIONS))
                .order_by(AuditLog.id)
            )).scalars().all()

        assert [row.action for row in rows] == list(FEATURE_AUDIT_ACTIONS)
        assert [row.details for row in rows] == [
            "previously_configured=false",
            "previously_configured=true",
            "previously_configured=true",
        ]
        for row in rows:
            assert row.user_id == 740013
            assert row.resource_type is None
            assert row.resource_id is None
            assert row.ip_address is None

        audit_payload = repr([
            (row.action, row.user_id, row.details, row.resource_type, row.resource_id)
            for row in rows
        ])
        emitted_logs = repr(audit_log.call_args_list)
        for file_id in ("fake-small-photo-id", "fake-large-photo-id"):
            assert file_id not in audit_payload
            assert file_id not in emitted_logs
