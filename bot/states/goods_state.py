from aiogram.filters.state import StatesGroup, State


class GoodsFSM(StatesGroup):
    """FSM for position (goods) and items management scenarios."""
    waiting_item_name_delete = State()
    waiting_item_name_show = State()
    waiting_bought_item_id = State()


class AddItemFSM(StatesGroup):
    """
    FSM for step-by-step creation of a position (product):
    1) name,
    2) description,
    3) price,
    4) category,
    5) mode (infinite or not),
    6) input product values (single / multiple).
    """
    waiting_item_name = State()
    waiting_item_description = State()
    waiting_item_price = State()
    waiting_category = State()
    waiting_infinity = State()
    waiting_values = State()
    waiting_single_value = State()


class UpdateItemFSM(StatesGroup):
    """
    FSM for updating an item:
    1) Add item values (stock) to an existing position.
    2) Full update (name, description, price, infinity/regular, values).
    """
    # Add values to an item
    waiting_item_name_for_amount_upd = State()
    waiting_item_values_upd = State()

    # Full update
    waiting_item_name_for_update = State()
    waiting_item_new_name = State()
    waiting_item_description = State()
    waiting_item_price = State()
    waiting_make_infinity = State()
    waiting_single_value = State()
    waiting_multiple_values = State()


class SaleFSM(StatesGroup):
    """
    FSM for setting or removing a time-limited sale on an item:
    1) item name,
    2) discount percent (0 removes the sale),
    3) duration in days.
    """
    waiting_item_name = State()
    waiting_percent = State()
    waiting_days = State()

