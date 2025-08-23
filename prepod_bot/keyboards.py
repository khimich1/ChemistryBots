from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

def get_teacher_keyboard():
    kb = [
        [KeyboardButton(text="👨‍🎓 Ученики онлайн")],
        [KeyboardButton(text="📈 Успеваемость")],
        [KeyboardButton(text="🛠 Управление заданиями")],
        [KeyboardButton(text="📣 Статистика рекламы")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


def get_manage_tasks_keyboard():
    kb = [
        [KeyboardButton(text="➕ Добавить")],
        [KeyboardButton(text="🛠 Исправить")],
        [KeyboardButton(text="⬅️ Назад")],
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)
