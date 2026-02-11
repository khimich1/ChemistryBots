from aiogram import Router, types
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from services.students import get_all_students
from services.groups import (
    get_students_with_group_access,
    get_all_students_with_plans,
    add_student_to_group,
    remove_student_from_group,
    is_student_in_group
)
from handlers import menu

router = Router()


def get_groups_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура для управления группами"""
    kb = [
        [KeyboardButton(text="⬅️ Назад в меню")],
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


@router.message(lambda m: m.text == "👥 Сформировать группы")
async def show_groups_menu(message: types.Message):
    """Показывает меню управления группами"""
    await message.answer(
        "👥 <b>Управление группами</b>\n\n"
        "Здесь вы можете добавить учеников в группу для доступа к тарифу 'Подписка на бота при занятии с преподавателем'.\n\n"
        "Выберите ученика из списка ниже:",
        parse_mode="HTML",
        reply_markup=get_groups_keyboard()
    )
    
    # Получаем ВСЕХ учеников с их тарифами
    students = get_all_students_with_plans()
    
    if not students:
        await message.answer("Пока нет зарегистрированных учеников.")
        return
    
    # Создаем inline клавиатуру с учениками
    keyboard_buttons = []
    for student in students:
        user_id = student["user_id"]
        label = student["label"]
        plan_name = student["plan_name"]
        is_added = is_student_in_group(user_id)
        
        # Показываем статус: добавлен/не добавлен
        status = "✅ Добавлен доступ" if is_added else "➕ Добавить доступ"
        callback_data = f"remove_group_{user_id}" if is_added else f"add_group_{user_id}"
        
        # Формируем текст кнопки: Имя - Тариф - Статус
        button_text = f"{label} - {plan_name} - {status}"
        
        keyboard_buttons.append([
            InlineKeyboardButton(
                text=button_text,
                callback_data=callback_data
            )
        ])
    
    # Добавляем кнопку обновления
    keyboard_buttons.append([
        InlineKeyboardButton(text="🔄 Обновить список", callback_data="refresh_groups")
    ])
    
    kb = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    
    await message.answer(
        "👥 <b>Список всех учеников:</b>\n\n"
        "Нажмите на ученика, чтобы изменить его статус доступа к групповому тарифу:",
        parse_mode="HTML",
        reply_markup=kb
    )


@router.callback_query(lambda c: c.data.startswith("add_group_"))
async def add_student_to_group_handler(cb: types.CallbackQuery):
    """Добавляет ученика в группу"""
    try:
        user_id = int(cb.data.split("_")[-1])
        add_student_to_group(user_id)
        
        # Получаем обновленный список
        students = get_all_students_with_plans()
        keyboard_buttons = []
        
        for student in students:
            s_user_id = student["user_id"]
            label = student["label"]
            plan_name = student["plan_name"]
            is_added = is_student_in_group(s_user_id)
            
            status = "✅ Добавлен доступ" if is_added else "➕ Добавить доступ"
            callback_data = f"remove_group_{s_user_id}" if is_added else f"add_group_{s_user_id}"
            
            # Формируем текст кнопки: Имя - Тариф - Статус
            button_text = f"{label} - {plan_name} - {status}"
            
            keyboard_buttons.append([
                InlineKeyboardButton(
                    text=button_text,
                    callback_data=callback_data
                )
            ])
        
        keyboard_buttons.append([
            InlineKeyboardButton(text="🔄 Обновить список", callback_data="refresh_groups")
        ])
        
        kb = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
        
        await cb.message.edit_text(
            "👥 <b>Список всех учеников:</b>\n\n"
            "Нажмите на ученика, чтобы изменить его статус доступа к групповому тарифу:",
            parse_mode="HTML",
            reply_markup=kb
        )
        
        await cb.answer("✅ Доступ добавлен!")
        
    except Exception as e:
        await cb.answer(f"❌ Ошибка: {e}", show_alert=True)


@router.callback_query(lambda c: c.data.startswith("remove_group_"))
async def remove_student_from_group_handler(cb: types.CallbackQuery):
    """Удаляет ученика из группы"""
    try:
        user_id = int(cb.data.split("_")[-1])
        remove_student_from_group(user_id)
        
        # Получаем обновленный список
        students = get_all_students_with_plans()
        keyboard_buttons = []
        
        for student in students:
            s_user_id = student["user_id"]
            label = student["label"]
            plan_name = student["plan_name"]
            is_added = is_student_in_group(s_user_id)
            
            status = "✅ Добавлен доступ" if is_added else "➕ Добавить доступ"
            callback_data = f"remove_group_{s_user_id}" if is_added else f"add_group_{s_user_id}"
            
            # Формируем текст кнопки: Имя - Тариф - Статус
            button_text = f"{label} - {plan_name} - {status}"
            
            keyboard_buttons.append([
                InlineKeyboardButton(
                    text=button_text,
                    callback_data=callback_data
                )
            ])
        
        keyboard_buttons.append([
            InlineKeyboardButton(text="🔄 Обновить список", callback_data="refresh_groups")
        ])
        
        kb = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
        
        await cb.message.edit_text(
            "👥 <b>Список всех учеников:</b>\n\n"
            "Нажмите на ученика, чтобы изменить его статус доступа к групповому тарифу:",
            parse_mode="HTML",
            reply_markup=kb
        )
        
        await cb.answer("❌ Доступ удален!")
        
    except Exception as e:
        await cb.answer(f"❌ Ошибка: {e}", show_alert=True)


@router.callback_query(lambda c: c.data == "refresh_groups")
async def refresh_groups_handler(cb: types.CallbackQuery):
    """Обновляет список групп"""
    await show_groups_menu(cb.message)
    await cb.answer("🔄 Список обновлен!")


@router.message(lambda m: m.text == "⬅️ Назад в меню")
async def back_to_menu(message: types.Message):
    """Возврат в главное меню"""
    await menu.cmd_start(message)
