from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton


def build_main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="О проекте"), KeyboardButton(text="Мой тариф")],
            [KeyboardButton(text="БОТ для учеников"), KeyboardButton(text="Бот для преподавателей")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите действие",
        one_time_keyboard=False,
    )


def build_confirm_all_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Все верно", callback_data="confirm_all"),
                InlineKeyboardButton(text="✏️ Исправить", callback_data="correct_all"),
            ]
        ]
    )


def build_correction_field_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✏️ Редактировать", callback_data="corr:edit"),
                InlineKeyboardButton(text="✅ Подтвердить", callback_data="corr:confirm"),
            ]
        ]
    )


def build_edit_profile_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Редактировать", callback_data="profile:edit")]
        ]
    )


def build_links_kb(student_url: str | None, teacher_url: str | None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    if student_url:
        row.append(InlineKeyboardButton(text="БОТ для учеников", url=student_url))
    if teacher_url:
        row.append(InlineKeyboardButton(text="Бот для преподавателей", url=teacher_url))
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)
