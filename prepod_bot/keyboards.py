from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

def get_teacher_keyboard():
    kb = [
        [KeyboardButton(text="👨‍🎓 Ученики онлайн")],
        [KeyboardButton(text="📈 Успеваемость")],
        [KeyboardButton(text="🛠 Управление заданиями")],
        [KeyboardButton(text="👥 Добавить в группу")],
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


def get_students_keyboard(students: list) -> InlineKeyboardMarkup:
    """Создает клавиатуру со списком учеников"""
    kb = []
    
    for student in students:
        # Создаем кнопку с именем ученика или ником
        label = student.get("label", f"ID {student['user_id']}")
        # Ограничиваем длину текста кнопки
        if len(label) > 30:
            label = label[:27] + "..."
        
        # Проверяем, добавлен ли ученик в группу
        is_in_group = student.get("is_in_group", False)
        status = "✅ В группе" if is_in_group else "➕ Добавить"
        
        kb.append([InlineKeyboardButton(
            text=f"{label} - {status}",
            callback_data=f"add_to_group:{student['user_id']}"
        )])
    
    # Добавляем кнопку "Назад"
    kb.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")])
    
    return InlineKeyboardMarkup(inline_keyboard=kb)
