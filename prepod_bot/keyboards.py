from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

def get_teacher_keyboard():
    kb = [
        [KeyboardButton(text="👨‍🎓 Ученики онлайн")],
        [KeyboardButton(text="📈 Успеваемость")],
        [KeyboardButton(text="➕ Добавить задание")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)
