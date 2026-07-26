from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.handlers.admin import broadcast as broadcast_mod
from bot.handlers.admin.broadcast import (
    broadcast_managers, _cancel_keyboard,
    send_message_callback_handler, broadcast_messages, cancel_broadcast_handler,
)
from bot.states import BroadcastFSM


@pytest.fixture(autouse=True)
def clean_manager_registry():
    """broadcast_managers is module-level state shared across tests."""
    broadcast_managers.clear()
    yield
    broadcast_managers.clear()


@pytest.fixture
def sending_message(make_message):
    """A message whose .answer returns an editable progress message."""
    def _make(text, user_id=900900):
        msg = make_message(text=text, user_id=user_id)
        progress = AsyncMock()
        msg.answer = AsyncMock(return_value=progress)
        msg.delete = AsyncMock()
        return msg, progress
    return _make


class TestCancelKeyboard:

    def test_has_a_single_cancel_button(self):
        markup = _cancel_keyboard()
        cbs = [b.callback_data for row in markup.inline_keyboard for b in row]
        assert cbs == ["cancel_broadcast"]


class TestBroadcastPrompt:

    async def test_prompt_sets_the_waiting_state(self, make_callback_query, fsm_context):
        call = make_callback_query(data="send_message", user_id=900901)
        await send_message_callback_handler(call, fsm_context)

        assert await fsm_context.get_state() == BroadcastFSM.waiting_message
        call.message.edit_text.assert_called_once()


class TestBroadcastSend:

    async def test_message_reaches_every_user(self, sending_message, fsm_context, user_factory):
        for tid in (910001, 910002, 910003):
            await user_factory(telegram_id=tid)

        msg, progress = sending_message("Hello everyone")
        await broadcast_messages(msg, fsm_context)

        recipients = {c.kwargs["chat_id"] for c in msg.bot.send_message.await_args_list}
        assert recipients == {910001, 910002, 910003}
        # The admin's own message is removed and replaced by a progress card.
        msg.delete.assert_awaited_once()
        progress.edit_text.assert_awaited()
        # The registry is released so the next broadcast can start.
        assert broadcast_managers == {}
        assert await fsm_context.get_state() is None

    async def test_html_is_sanitized_before_sending(self, sending_message, fsm_context,
                                                    user_factory):
        await user_factory(telegram_id=910010)

        msg, _ = sending_message("<b>bold</b> <script>alert(1)</script>")
        await broadcast_messages(msg, fsm_context)

        sent_text = msg.bot.send_message.await_args.kwargs["text"]
        assert "<script>" not in sent_text
        assert "<b>bold</b>" in sent_text   # Telegram-safe markup survives

    async def test_invalid_markup_is_rejected_without_sending(self, sending_message, fsm_context,
                                                              user_factory):
        await user_factory(telegram_id=910020)

        msg, _ = sending_message("<b>unbalanced")
        await broadcast_messages(msg, fsm_context)

        msg.bot.send_message.assert_not_awaited()
        assert broadcast_managers == {}
        assert await fsm_context.get_state() is None

    async def test_overlong_text_is_rejected(self, sending_message, fsm_context, user_factory):
        await user_factory(telegram_id=910030)

        msg, _ = sending_message("x" * 4097)
        await broadcast_messages(msg, fsm_context)

        msg.bot.send_message.assert_not_awaited()

    async def test_a_second_broadcast_is_refused_while_one_runs(self, sending_message,
                                                                fsm_context, user_factory):
        await user_factory(telegram_id=910040)
        admin_id = 900910
        broadcast_managers[admin_id] = None  # a send is already in flight

        msg, _ = sending_message("Hello", user_id=admin_id)
        await broadcast_messages(msg, fsm_context)

        msg.bot.send_message.assert_not_awaited()
        msg.delete.assert_not_awaited()
        # The in-flight entry is left alone for its owner to clean up.
        assert admin_id in broadcast_managers

    async def test_two_admins_do_not_share_a_slot(self, sending_message, fsm_context,
                                                  user_factory):
        await user_factory(telegram_id=910050)
        broadcast_managers[111] = None  # another admin is busy

        msg, _ = sending_message("Hello", user_id=222)
        await broadcast_messages(msg, fsm_context)

        msg.bot.send_message.assert_awaited()
        assert 222 not in broadcast_managers   # released after finishing
        assert 111 in broadcast_managers       # the other admin is untouched

    async def test_a_failing_progress_edit_does_not_abort_the_send(self, sending_message,
                                                                   fsm_context, user_factory):
        from aiogram.exceptions import TelegramBadRequest

        for tid in (910060, 910061):
            await user_factory(telegram_id=tid)

        msg, progress = sending_message("Hello")
        progress.edit_text = AsyncMock(
            side_effect=TelegramBadRequest(method=MagicMock(), message="not modified")
        )

        await broadcast_messages(msg, fsm_context)

        assert msg.bot.send_message.await_count == 2
        assert broadcast_managers == {}

    async def test_an_unexpected_failure_still_releases_the_slot(self, sending_message,
                                                                 fsm_context, user_factory):
        await user_factory(telegram_id=910070)

        msg, _ = sending_message("Hello")
        with patch.object(broadcast_mod, 'get_all_users',
                          new_callable=AsyncMock, side_effect=RuntimeError("db down")):
            await broadcast_messages(msg, fsm_context)

        assert broadcast_managers == {}
        assert await fsm_context.get_state() is None


class TestCancelBroadcast:

    async def test_cancel_stops_the_callers_manager(self, make_callback_query):
        manager = MagicMock()
        broadcast_managers[900920] = manager

        call = make_callback_query(data="cancel_broadcast", user_id=900920)
        await cancel_broadcast_handler(call)

        manager.cancel.assert_called_once()
        call.answer.assert_called_once()

    async def test_cancel_without_a_running_broadcast_just_warns(self, make_callback_query):
        call = make_callback_query(data="cancel_broadcast", user_id=900921)
        await cancel_broadcast_handler(call)

        call.answer.assert_called_once()

    async def test_cancel_does_not_touch_another_admins_broadcast(self, make_callback_query):
        other = MagicMock()
        broadcast_managers[111] = other

        call = make_callback_query(data="cancel_broadcast", user_id=222)
        await cancel_broadcast_handler(call)

        other.cancel.assert_not_called()

    async def test_a_reserved_but_unbuilt_slot_is_not_cancellable(self, make_callback_query):
        """The slot holds None between reservation and manager construction."""
        broadcast_managers[900922] = None

        call = make_callback_query(data="cancel_broadcast", user_id=900922)
        await cancel_broadcast_handler(call)

        call.answer.assert_called_once()
