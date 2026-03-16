from aiogram.fsm.state import StatesGroup, State


class ReviewFSM(StatesGroup):
    waiting_rating = State()
    waiting_text = State()
