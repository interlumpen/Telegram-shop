from aiogram.filters.state import StatesGroup, State


class RoleMgmtFSM(StatesGroup):
    waiting_role_name = State()
    waiting_role_perms = State()
    editing_role_name = State()
    editing_role_perms = State()
