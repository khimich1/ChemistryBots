from aiogram.fsm.state import StatesGroup, State


class TariffForm(StatesGroup):
    name = State()
    discipline = State()
    moniker = State()

    confirming = State()
    correcting = State()
    editing_field = State()
