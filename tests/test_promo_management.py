import datetime

import pytest
from sqlalchemy import select

from bot.database.main import Database
from bot.database.methods.read import get_promo_code
from bot.database.models.main import PromoCodes
from bot.handlers.admin.promo_management import (
    _promo_id_arg, _promo_list_label, _show_promo_view,
    promo_management_handler, navigate_promos,
    view_promo, toggle_promo, confirm_delete_promo, delete_promo_confirmed,
    promo_create_start, promo_receive_code, promo_receive_type,
    promo_receive_value, promo_receive_max_uses, promo_receive_expires,
    promo_binding_type_chosen, promo_receive_binding_name,
)
from bot.states import PromoFSM


async def _make_promo(code="SAVE10", discount_type="percent", value=10, **kw):
    """Insert a promo directly and return its id."""
    async with Database().session() as s:
        promo = PromoCodes(
            code=code.upper(), discount_type=discount_type, discount_value=value,
            max_uses=kw.pop("max_uses", 0), current_uses=kw.pop("current_uses", 0),
            is_active=kw.pop("is_active", True), **kw,
        )
        s.add(promo)
        await s.flush()
        return promo.id


async def _fetch(code):
    async with Database().session() as s:
        return (await s.execute(
            select(PromoCodes).where(PromoCodes.code == code.upper())
        )).scalars().first()


async def _run_creation_flow(make_message, make_callback_query, fsm_context, *,
                             code, dtype, value, max_uses, expires):
    """Drive the FSM from the code prompt down to the binding question."""
    await promo_receive_code(make_message(text=code, user_id=1), fsm_context)
    await promo_receive_type(
        make_callback_query(data=f"promo_type_{dtype}", user_id=1), fsm_context
    )
    await promo_receive_value(make_message(text=value, user_id=1), fsm_context)
    await promo_receive_max_uses(make_message(text=max_uses, user_id=1), fsm_context)
    await promo_receive_expires(make_message(text=expires, user_id=1), fsm_context)


class TestPromoIdArg:

    @pytest.mark.parametrize("data,expected", [
        ("promo_v_7", 7),
        ("promo_toggle_12", 12),
        ("promo_d_3", 3),
        ("promo_dc_99", 99),
        ("promo_v_abc", None),   # non-numeric id
        ("promo_v_", None),      # empty id
        ("promo_v", None),       # truncated payload
        ("", None),
    ])
    def test_parsing(self, data, expected):
        assert _promo_id_arg(data) == expected


class TestPromoListLabel:

    def test_dangling_promo_is_flagged(self):
        label = _promo_list_label(
            {"code": "ORPHAN", "is_active": True, "current_uses": 0,
             "max_uses": 0, "dangling": True}
        )
        assert label.startswith("⚠️ ")
        assert "∞" in label  # max_uses=0 renders as unlimited

    @pytest.mark.parametrize("is_active,icon", [(True, "✅"), (False, "⛔")])
    def test_state_icon(self, is_active, icon):
        label = _promo_list_label(
            {"code": "C", "is_active": is_active, "current_uses": 2, "max_uses": 5}
        )
        assert icon in label
        assert "(2/5)" in label


class TestPromoList:

    async def test_empty_list_offers_creation(self, make_callback_query, fsm_context):
        call = make_callback_query(data="promo_mgmt", user_id=900500)
        await promo_management_handler(call, fsm_context)

        cbs = [
            b.callback_data
            for row in call.message.edit_text.call_args[1]["reply_markup"].inline_keyboard
            for b in row
        ]
        assert cbs == ["promo_create", "console"]

    async def test_existing_promos_are_listed(self, make_callback_query, fsm_context):
        promo_id = await _make_promo(code="LISTED")

        call = make_callback_query(data="promo_mgmt", user_id=900501)
        await promo_management_handler(call, fsm_context)

        markup = call.message.edit_text.call_args[1]["reply_markup"]
        cbs = [b.callback_data for row in markup.inline_keyboard for b in row]
        assert f"promo_v_{promo_id}" in cbs
        # Create and Back stay pinned at the bottom.
        assert cbs[-2:] == ["promo_create", "console"]

    async def test_navigate_renders_the_requested_page(self, make_callback_query, fsm_context):
        await _make_promo(code="PAGED")

        call = make_callback_query(data="promos-page_0", user_id=900502)
        await navigate_promos(call, fsm_context)

        call.message.edit_text.assert_called_once()
        assert call.message.edit_text.call_args[1]["reply_markup"] is not None

    async def test_malformed_page_payload_is_rejected(self, make_callback_query, fsm_context):
        call = make_callback_query(data="promos-page_abc", user_id=900503)
        await navigate_promos(call, fsm_context)

        call.answer.assert_called_once()
        call.message.edit_text.assert_not_called()


class TestViewPromo:

    async def test_detail_view_renders_actions(self, make_callback_query, fsm_context):
        promo_id = await _make_promo(code="VIEWME")

        call = make_callback_query(data=f"promo_v_{promo_id}", user_id=900510)
        await view_promo(call, fsm_context)

        markup = call.message.edit_text.call_args[1]["reply_markup"]
        cbs = [b.callback_data for row in markup.inline_keyboard for b in row]
        assert cbs == [f"promo_toggle_{promo_id}", f"promo_d_{promo_id}", "promo_mgmt"]

    async def test_missing_promo_answers_instead_of_rendering(self, make_callback_query, fsm_context):
        call = make_callback_query(data="promo_v_424242", user_id=900511)
        await view_promo(call, fsm_context)

        call.answer.assert_called_once()
        call.message.edit_text.assert_not_called()

    async def test_malformed_id_is_rejected(self, make_callback_query, fsm_context):
        call = make_callback_query(data="promo_v_xyz", user_id=900512)
        await view_promo(call, fsm_context)

        call.answer.assert_called_once()
        call.message.edit_text.assert_not_called()

    async def test_dangling_category_binding_is_labelled(self, make_callback_query, category_factory):
        """A scoped promo whose category was deleted keeps scope but loses the id."""
        from bot.database.methods.create import create_category
        from bot.database.methods.delete import delete_category
        from bot.database.models.main import Categories

        await create_category("BoundCat")
        async with Database().session() as s:
            cat_id = (await s.execute(
                select(Categories.id).where(Categories.name == "BoundCat")
            )).scalar()
        promo_id = await _make_promo(code="SCOPED", scope="category", category_id=cat_id)

        await delete_category("BoundCat")

        message = make_callback_query(data="x").message
        assert await _show_promo_view(message, promo_id) is True
        # Rendered without raising even though the binding target is gone.
        assert message.edit_text.call_args[0][0]

    async def test_show_promo_view_reports_a_missing_promo(self, make_callback_query):
        message = make_callback_query(data="x").message
        assert await _show_promo_view(message, 999999) is False
        message.edit_text.assert_not_called()


class TestTogglePromo:

    async def test_toggle_flips_and_rerenders(self, make_callback_query, fsm_context):
        promo_id = await _make_promo(code="TOGGLED", is_active=True)

        call = make_callback_query(data=f"promo_toggle_{promo_id}", user_id=900520)
        await toggle_promo(call, fsm_context)

        assert (await _fetch("TOGGLED")).is_active is False
        call.message.edit_text.assert_called_once()  # detail view refreshed

        await toggle_promo(call, fsm_context)
        assert (await _fetch("TOGGLED")).is_active is True

    async def test_toggling_a_missing_promo_changes_nothing(self, make_callback_query, fsm_context):
        call = make_callback_query(data="promo_toggle_424242", user_id=900521)
        await toggle_promo(call, fsm_context)

        call.answer.assert_called_once()
        call.message.edit_text.assert_not_called()


class TestDeletePromo:

    async def test_confirmation_screen_offers_yes_and_no(self, make_callback_query, fsm_context):
        promo_id = await _make_promo(code="DELME")

        call = make_callback_query(data=f"promo_d_{promo_id}", user_id=900530)
        await confirm_delete_promo(call, fsm_context)

        markup = call.message.edit_text.call_args[1]["reply_markup"]
        cbs = [b.callback_data for row in markup.inline_keyboard for b in row]
        assert cbs == [f"promo_dc_{promo_id}", f"promo_v_{promo_id}"]
        # Nothing is deleted until the admin confirms.
        assert await _fetch("DELME") is not None

    async def test_confirmed_delete_removes_the_promo(self, make_callback_query, fsm_context):
        promo_id = await _make_promo(code="GONE")

        call = make_callback_query(data=f"promo_dc_{promo_id}", user_id=900531)
        await delete_promo_confirmed(call, fsm_context)

        assert await _fetch("GONE") is None
        call.answer.assert_called_once()

    async def test_malformed_delete_payload_deletes_nothing(self, make_callback_query, fsm_context):
        await _make_promo(code="SAFE")

        call = make_callback_query(data="promo_dc_oops", user_id=900532)
        await delete_promo_confirmed(call, fsm_context)

        call.answer.assert_called_once()
        assert await _fetch("SAFE") is not None


class TestPromoCreationFlow:

    async def test_start_sets_the_code_state(self, make_callback_query, fsm_context):
        call = make_callback_query(data="promo_create", user_id=900540)
        await promo_create_start(call, fsm_context)

        assert await fsm_context.get_state() == PromoFSM.waiting_code

    async def test_percent_promo_bound_to_a_category(self, make_message, make_callback_query,
                                                     fsm_context, category_factory):
        await category_factory("PromoCat")

        await _run_creation_flow(
            make_message, make_callback_query, fsm_context,
            code="summer-2026", dtype="percent", value="15", max_uses="5",
            expires="2026-12-31",
        )
        assert await fsm_context.get_state() == PromoFSM.waiting_binding_type

        await promo_binding_type_chosen(
            make_callback_query(data="promo_bind_category", user_id=1), fsm_context
        )
        await promo_receive_binding_name(make_message(text="PromoCat", user_id=1), fsm_context)

        promo = await _fetch("SUMMER-2026")
        assert promo is not None
        assert promo.code == "SUMMER-2026"        # normalized to upper case
        assert promo.discount_type == "percent"
        assert promo.discount_value == 15
        assert promo.max_uses == 5
        assert promo.category_id is not None
        # The named day is the last valid one, so expiry rolls to the next midnight.
        assert promo.expires_at.date() == datetime.date(2027, 1, 1)
        assert await fsm_context.get_state() is None

    async def test_fixed_promo_bound_to_an_item(self, make_message, make_callback_query,
                                                fsm_context, item_factory):
        await item_factory(name="BoundItem", price=100, values=[("v", False)])

        await _run_creation_flow(
            make_message, make_callback_query, fsm_context,
            code="ITEM50", dtype="fixed", value="50", max_uses="0", expires="0",
        )
        await promo_binding_type_chosen(
            make_callback_query(data="promo_bind_item", user_id=1), fsm_context
        )
        await promo_receive_binding_name(make_message(text="BoundItem", user_id=1), fsm_context)

        promo = await _fetch("ITEM50")
        assert promo.discount_type == "fixed"
        assert promo.item_id is not None
        assert promo.expires_at is None   # "0" means never expires
        assert promo.max_uses == 0

    async def test_unbound_promo_skips_the_binding_name(self, make_message, make_callback_query,
                                                        fsm_context):
        await _run_creation_flow(
            make_message, make_callback_query, fsm_context,
            code="GLOBAL10", dtype="percent", value="10", max_uses="0", expires="0",
        )
        await promo_binding_type_chosen(
            make_callback_query(data="promo_bind_none", user_id=1), fsm_context
        )

        promo = await _fetch("GLOBAL10")
        assert promo.category_id is None
        assert promo.item_id is None

    async def test_balance_promo_is_created_without_asking_about_binding(
            self, make_message, make_callback_query, fsm_context):
        await _run_creation_flow(
            make_message, make_callback_query, fsm_context,
            code="TOPUP100", dtype="balance", value="100", max_uses="1", expires="0",
        )

        promo = await _fetch("TOPUP100")
        assert promo is not None
        assert promo.discount_type == "balance"
        # No binding question was asked — the flow already finished.
        assert await fsm_context.get_state() is None


class TestPromoCreationRejections:

    @pytest.mark.parametrize("bad_code", [
        "with space",
        "sym!bol",
        "",
        "x" * 51,   # over the 50-char cap
    ])
    async def test_invalid_code_keeps_the_state(self, make_message, fsm_context, bad_code):
        await fsm_context.set_state(PromoFSM.waiting_code)
        await promo_receive_code(make_message(text=bad_code, user_id=1), fsm_context)

        # Still waiting for a code — the flow did not advance.
        assert await fsm_context.get_state() == PromoFSM.waiting_code

    async def test_duplicate_code_is_refused(self, make_message, fsm_context):
        await _make_promo(code="TAKEN")

        await fsm_context.set_state(PromoFSM.waiting_code)
        await promo_receive_code(make_message(text="taken", user_id=1), fsm_context)

        assert await fsm_context.get_state() == PromoFSM.waiting_code
        assert await get_promo_code("TAKEN") is not None

    @pytest.mark.parametrize("dtype,bad_value", [
        ("percent", "0"),
        ("percent", "-5"),
        ("percent", "101"),   # a percent discount above 100 would mint balance
        ("fixed", "abc"),
        ("fixed", ""),
    ])
    async def test_invalid_value_keeps_the_state(self, make_message, make_callback_query,
                                                 fsm_context, dtype, bad_value):
        await promo_receive_code(make_message(text="VALCHECK", user_id=1), fsm_context)
        await promo_receive_type(
            make_callback_query(data=f"promo_type_{dtype}", user_id=1), fsm_context
        )
        await promo_receive_value(make_message(text=bad_value, user_id=1), fsm_context)

        assert await fsm_context.get_state() == PromoFSM.waiting_value

    @pytest.mark.parametrize("bad_max_uses", ["-1", "abc", "1.5"])
    async def test_invalid_max_uses_keeps_the_state(self, make_message, make_callback_query,
                                                    fsm_context, bad_max_uses):
        await promo_receive_code(make_message(text="MAXCHECK", user_id=1), fsm_context)
        await promo_receive_type(
            make_callback_query(data="promo_type_percent", user_id=1), fsm_context
        )
        await promo_receive_value(make_message(text="10", user_id=1), fsm_context)
        await promo_receive_max_uses(make_message(text=bad_max_uses, user_id=1), fsm_context)

        assert await fsm_context.get_state() == PromoFSM.waiting_max_uses

    @pytest.mark.parametrize("bad_date", ["31-12-2026", "2026/12/31", "tomorrow", "2026-13-01"])
    async def test_invalid_expiry_keeps_the_state(self, make_message, make_callback_query,
                                                  fsm_context, bad_date):
        await promo_receive_code(make_message(text="DATECHECK", user_id=1), fsm_context)
        await promo_receive_type(
            make_callback_query(data="promo_type_percent", user_id=1), fsm_context
        )
        await promo_receive_value(make_message(text="10", user_id=1), fsm_context)
        await promo_receive_max_uses(make_message(text="0", user_id=1), fsm_context)
        await promo_receive_expires(make_message(text=bad_date, user_id=1), fsm_context)

        assert await fsm_context.get_state() == PromoFSM.waiting_expires
        assert await _fetch("DATECHECK") is None

    async def test_unknown_category_does_not_create_the_promo(self, make_message,
                                                              make_callback_query, fsm_context):
        await _run_creation_flow(
            make_message, make_callback_query, fsm_context,
            code="NOCAT", dtype="percent", value="10", max_uses="0", expires="0",
        )
        await promo_binding_type_chosen(
            make_callback_query(data="promo_bind_category", user_id=1), fsm_context
        )
        await promo_receive_binding_name(make_message(text="NoSuchCategory", user_id=1), fsm_context)

        assert await _fetch("NOCAT") is None
        assert await fsm_context.get_state() == PromoFSM.waiting_binding_name

    async def test_unknown_item_does_not_create_the_promo(self, make_message,
                                                          make_callback_query, fsm_context):
        await _run_creation_flow(
            make_message, make_callback_query, fsm_context,
            code="NOITEM", dtype="fixed", value="10", max_uses="0", expires="0",
        )
        await promo_binding_type_chosen(
            make_callback_query(data="promo_bind_item", user_id=1), fsm_context
        )
        await promo_receive_binding_name(make_message(text="NoSuchItem", user_id=1), fsm_context)

        assert await _fetch("NOITEM") is None
        assert await fsm_context.get_state() == PromoFSM.waiting_binding_name
