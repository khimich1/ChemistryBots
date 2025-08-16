from aiogram.fsm.state import StatesGroup, State


class EditStudent(StatesGroup):
    waiting_new_username = State()
    waiting_new_fullname = State()

