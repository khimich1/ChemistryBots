import os
from aiogram import Router, types
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from services.students import get_all_students, update_user_profile, clear_hide_reason_all, set_hide_reason
from services.govr_report import make_pdf_report
from states import EditStudent

router = Router()


def _students_kb():
    students = get_all_students()
    # Кнопки в 1 столбец
    keyboard = [[InlineKeyboardButton(text=s["label"], callback_data=f"student_{s['user_id']}")] for s in students]
    # Кнопка "Показать всех" в конце
    keyboard.append([InlineKeyboardButton(text="Показать всех", callback_data="students_show_all")])
    # Если список пуст — добавим заглушку
    if not keyboard:
        keyboard = [[InlineKeyboardButton(text="Список пуст", callback_data="noop")]]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def _student_menu_kb(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📈 Успеваемость", callback_data=f"stud_{user_id}_progress")],
        [InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"stud_{user_id}_edit")],
        [InlineKeyboardButton(text="🗑️ Удалить из списка", callback_data=f"stud_{user_id}_delete")],
        [InlineKeyboardButton(text="⬅️ Назад к списку", callback_data="students_back")],
    ])


@router.message(lambda m: m.text == "📈 Успеваемость")
async def report_entry(message: types.Message):
    await message.answer("Выберите ученика:", reply_markup=_students_kb())


@router.callback_query(lambda c: c.data == "students_back")
async def students_back(cb: types.CallbackQuery):
    try:
        await cb.message.edit_text("Выберите ученика:", reply_markup=_students_kb())
    except Exception:
        await cb.message.answer("Выберите ученика:", reply_markup=_students_kb())
    await cb.answer()


@router.callback_query(lambda c: c.data == "students_show_all")
async def students_show_all(cb: types.CallbackQuery):
    changed = clear_hide_reason_all()
    text = "Сброшены скрытия у всех учеников." if changed else "Никто не был скрыт."
    try:
        await cb.message.edit_text("Выберите ученика:", reply_markup=_students_kb())
    except Exception:
        await cb.message.answer("Выберите ученика:", reply_markup=_students_kb())
    await cb.answer(text, show_alert=True)


@router.callback_query(lambda c: c.data and c.data.startswith("student_"))
async def student_selected(cb: types.CallbackQuery):
    try:
        user_id = int(cb.data.split("_", 1)[1])
    except Exception:
        await cb.answer("Ошибка ID", show_alert=True)
        return
    try:
        await cb.message.edit_text(f"Ученик ID {user_id}. Выберите действие:", reply_markup=_student_menu_kb(user_id))
    except Exception:
        await cb.message.answer(f"Ученик ID {user_id}. Выберите действие:", reply_markup=_student_menu_kb(user_id))
    await cb.answer()


@router.callback_query(lambda c: c.data and c.data.endswith("_progress"))
async def student_progress(cb: types.CallbackQuery):
    user_id = int(cb.data.split("_", 2)[1])
    # имя для шапки берём из подписи кнопки / либо пустое
    # Сгенерируем PDF во временный файл
    filename = f"report_{user_id}.pdf"
    path = make_pdf_report(user_id, fullname=None, filename=filename)
    try:
        await cb.message.answer_document(document=types.FSInputFile(path), caption=f"Отчёт по ученику ID {user_id}")
    except Exception as e:
        await cb.message.answer(f"Не удалось отправить отчёт: {e}")
    finally:
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except Exception:
            pass
    await cb.answer()


# === Редактирование профиля ===
def _edit_menu_kb(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Изменить username", callback_data=f"stud_{user_id}_edit_username")],
        [InlineKeyboardButton(text="Изменить имя (full_name)", callback_data=f"stud_{user_id}_edit_fullname")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"student_{user_id}")],
    ])


@router.callback_query(lambda c: c.data and c.data.endswith("_edit"))
async def edit_menu(cb: types.CallbackQuery):
    user_id = int(cb.data.split("_", 2)[1])
    try:
        await cb.message.edit_text("Редактирование профиля ученика:", reply_markup=_edit_menu_kb(user_id))
    except Exception:
        await cb.message.answer("Редактирование профиля ученика:", reply_markup=_edit_menu_kb(user_id))
    await cb.answer()


@router.callback_query(lambda c: c.data and c.data.endswith("_edit_username"))
async def ask_new_username(cb: types.CallbackQuery, state: FSMContext):
    user_id = int(cb.data.split("_", 2)[1])
    await state.update_data(edit_user_id=user_id)
    await state.set_state(EditStudent.waiting_new_username)
    await cb.message.answer("Пришлите новый username (можно пустую строку, чтобы очистить):")
    await cb.answer()


@router.callback_query(lambda c: c.data and c.data.endswith("_edit_fullname"))
async def ask_new_fullname(cb: types.CallbackQuery, state: FSMContext):
    user_id = int(cb.data.split("_", 2)[1])
    await state.update_data(edit_user_id=user_id)
    await state.set_state(EditStudent.waiting_new_fullname)
    await cb.message.answer("Пришлите новое имя (full_name). Пустая строка — очистить значение:")
    await cb.answer()


@router.message(EditStudent.waiting_new_username)
async def save_new_username(m: types.Message, state: FSMContext):
    data = await state.get_data()
    user_id = int(data["edit_user_id"])  # кому меняем
    new_username = (m.text or "").strip()
    update_user_profile(user_id, username=new_username)
    await state.clear()
    await m.answer("Username обновлён. Возвращаю список учеников...", reply_markup=_students_kb())


@router.message(EditStudent.waiting_new_fullname)
async def save_new_fullname(m: types.Message, state: FSMContext):
    data = await state.get_data()
    user_id = int(data["edit_user_id"])  # кому меняем
    new_fullname = (m.text or "").strip()
    update_user_profile(user_id, full_name=new_fullname)
    await state.clear()
    await m.answer("Имя обновлено. Возвращаю список учеников...", reply_markup=_students_kb())


@router.callback_query(lambda c: c.data and c.data.endswith("_delete"))
async def hide_student(cb: types.CallbackQuery):
    user_id = int(cb.data.split("_", 2)[1])
    set_hide_reason(user_id, reason="hidden_by_teacher")
    # Обновляем список
    try:
        await cb.message.edit_text("Выберите ученика:", reply_markup=_students_kb())
    except Exception:
        await cb.message.answer("Выберите ученика:", reply_markup=_students_kb())
    await cb.answer("Ученик скрыт из списка. Используйте 'Показать всех' чтобы вернуть.", show_alert=True)
