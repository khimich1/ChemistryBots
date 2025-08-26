from aiogram import Router, types
from aiogram.filters import Command
from keyboards import get_teacher_keyboard, get_students_keyboard
from services.acquisition import get_ad_stats
from services.students import get_all_students
from services.groups import add_student_to_group, is_student_in_group

router = Router()

@router.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "Привет! Я помощник преподавателя. Выберите действие:",
        reply_markup=get_teacher_keyboard()
    )


@router.message(lambda m: m.text == "👥 Добавить в группу")
async def show_students_list(message: types.Message):
    """Показывает список всех зарегистрированных учеников"""
    students = get_all_students()
    
    if not students:
        await message.answer("Пока нет зарегистрированных учеников.")
        return
    
    # Добавляем информацию о том, кто уже в группе
    for student in students:
        student["is_in_group"] = is_student_in_group(student["user_id"])
    
    keyboard = get_students_keyboard(students)
    await message.answer(
        "Список всех зарегистрированных учеников:\n\n"
        "Нажмите на ученика, чтобы добавить его в группу для доступа к тарифу 'Групповые':",
        reply_markup=keyboard
    )


@router.callback_query(lambda c: c.data.startswith("add_to_group:"))
async def add_student_to_group_handler(callback: types.CallbackQuery):
    """Обработчик добавления ученика в группу"""
    try:
        user_id = int(callback.data.split(":")[1])
        
        # Получаем информацию об ученике
        students = get_all_students()
        student_info = None
        for student in students:
            if student["user_id"] == user_id:
                student_info = student
                break
        
        if not student_info:
            await callback.answer("Ученик не найден!")
            return
        
        # Проверяем, не добавлен ли уже ученик
        if is_student_in_group(user_id):
            await callback.answer("Ученик уже в группе!")
            return
        
        # Добавляем ученика в группу
        add_student_to_group(user_id)
        
        student_name = student_info.get("label", f"ID {user_id}")
        await callback.answer(f"✅ {student_name} добавлен в группу! Теперь он может купить тариф 'Групповые'.")
        
        # Обновляем список учеников
        await show_students_list(callback.message)
        
    except Exception as e:
        await callback.answer(f"Ошибка: {e}", show_alert=True)


@router.callback_query(lambda c: c.data == "back_to_main")
async def back_to_main_handler(callback: types.CallbackQuery):
    """Возврат в главное меню"""
    await callback.message.delete()
    await callback.message.answer(
        "Выберите действие:",
        reply_markup=get_teacher_keyboard()
    )


@router.message(lambda m: m.text == "📣 Статистика рекламы")
async def show_ads_stats(message: types.Message):
    rows = get_ad_stats()
    if not rows:
        await message.answer("Пока нет данных по рекламе.")
        return
    # Подготовим данные и итоги
    data = []
    total_started = 0
    total_subscribed = 0
    for tag, started, subscribed in rows:
        shown_tag = tag if tag and tag != "(empty)" else "(без метки)"
        total_started += int(started or 0)
        total_subscribed += int(subscribed or 0)
        cr = (int(subscribed or 0) * 100.0 / int(started or 1)) if int(started or 0) else 0.0
        data.append((shown_tag, int(started or 0), int(subscribed or 0), cr))

    # Сортировка по старте desc
    data.sort(key=lambda r: r[1], reverse=True)

    # Вычислим ширины колонок
    tag_w = max(10, max(len(r[0]) for r in data))
    s_w = max(7, len("started"))
    sub_w = max(10, len("subscribed"))
    cr_w = len("CR%")

    def row_line(tag: str, s: int, sub: int, cr: float) -> str:
        return f"{tag.ljust(tag_w)}  {str(s).rjust(s_w)}  {str(sub).rjust(sub_w)}  {int(round(cr)):>3}%"

    total_cr = (total_subscribed * 100.0 / total_started) if total_started else 0.0
    header = f"{'tag'.ljust(tag_w)}  {'started'.rjust(s_w)}  {'subscribed'.rjust(sub_w)}  CR%"
    lines = [
        "<b>Статистика по меткам</b>",
        "<pre>",
        header,
        "-" * (tag_w + s_w + sub_w + 8),
        row_line("ИТОГО", total_started, total_subscribed, total_cr),
        "",
    ]
    for tag, s, sub, cr in data:
        lines.append(row_line(tag, s, sub, cr))
    lines.append("</pre>")

    # Подсказка, если много строк без метки
    if any(tag == "(без метки)" for tag, *_ in data):
        lines.append("Пользователи без метки заходили не по deep-link. Используйте ссылку вида https://t.me/ИмяБота?start=ads1")

    await message.answer("\n".join(lines), parse_mode="HTML")
