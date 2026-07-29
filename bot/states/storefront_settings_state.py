from aiogram.filters.state import StatesGroup, State


class StorefrontSettingsFSM(StatesGroup):
    waiting_start_image = State()
    confirming_start_image_removal = State()
