from aiogram.fsm.state import StatesGroup, State


class CartStates(StatesGroup):
    viewing_cart = State()
