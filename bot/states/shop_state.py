from aiogram.filters.state import State, StatesGroup


class ShopStates(StatesGroup):
    """
    FSM states for the shopping section (personal purchases list).
    """
    viewing_goods = State()
    viewing_bought_items = State()
    viewing_categories = State()
    waiting_search_query = State()
    viewing_search_results = State()
