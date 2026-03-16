from aiogram.fsm.state import StatesGroup, State


class PromoFSM(StatesGroup):
    waiting_code = State()
    waiting_type = State()
    waiting_value = State()
    waiting_max_uses = State()
    waiting_expires = State()
    waiting_binding_type = State()
    waiting_binding_name = State()
    waiting_redeem_code = State()
