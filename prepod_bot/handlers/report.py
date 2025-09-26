import os
import sys
from aiogram import Router, types
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import StateFilter

from services.students import (
    get_all_students, update_user_profile, clear_hide_reason_all, set_hide_reason,
    build_user_progress_text, build_user_summary_text,
    build_user_progress_text_ege, build_user_progress_text_oge, build_user_flashcards_text, build_user_oral_text,
)
from services.groups import get_all_group_numbers, get_work_group_members, get_all_students_with_plans
from states import EditStudent, ReportSearch

# Добавляем путь к модулю в parent_bot
parent_services_path = os.path.join(os.path.dirname(__file__), "..", "..", "parent_bot", "bot", "services")
sys.path.insert(0, parent_services_path)
from filename_generator import get_filename_for_user, get_user_display_name

router = Router()


def _report_students_kb(students: list, *, page: int = 1, page_size: int = 30) -> InlineKeyboardMarkup:
    total = max(0, len(students))
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = max(1, min(page, total_pages))
    start = (page - 1) * page_size
    end = min(start + page_size, total)

    rows: list[list[InlineKeyboardButton]] = []
    for s in students[start:end]:
        label = s.get("label") or s.get("full_name") or s.get("username") or f"ID {s.get('user_id')}"
        if len(label) > 30:
            label = label[:27] + "…"
        rows.append([InlineKeyboardButton(text=label, callback_data=f"student_{s['user_id']}")])

    # Контролы: Поиск | Список групп
    rows.append([
        InlineKeyboardButton(text="🔎 Поиск", callback_data="report_search"),
        InlineKeyboardButton(text="📂 Список групп", callback_data="report_groups_list"),
    ])

    # Навигация по страницам
    if total_pages > 1:
        prev_page = page - 1 if page > 1 else page
        next_page = page + 1 if page < total_pages else page
        rows.append([
            InlineKeyboardButton(text="⬅️", callback_data=f"report_page:{prev_page}"),
            InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="report_page:noop"),
            InlineKeyboardButton(text="➡️", callback_data=f"report_page:{next_page}"),
        ])

    rows.append([InlineKeyboardButton(text="⬅️ В главное меню", callback_data="back_to_main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _filter_students(students: list, query: str) -> list:
    q = (query or "").strip().lower()
    if not q:
        return students
    q_no_at = q[1:] if q.startswith("@") else q
    out = []
    for s in students:
        label = (s.get("label") or "").lower()
        username = (s.get("username") or "").lower()
        username_no_at = username[1:] if username.startswith("@") else username
        full_name = (s.get("full_name") or "").lower()
        if any(qp in label or qp in username or qp in username_no_at or qp in full_name for qp in {q, q_no_at}):
            out.append(s)
    return out


def _report_groups_kb(groups: list[int]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=f"Группа {g}", callback_data=f"rep_open_group:{g}")] for g in groups]
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="students_back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _report_group_members_kb(members: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for s in members:
        label = s.get("label") or s.get("full_name") or s.get("username") or f"ID {s.get('user_id')}"
        if len(label) > 30:
            label = label[:27] + "…"
        rows.append([InlineKeyboardButton(text=label, callback_data=f"rep_open_student:{s.get('user_id')}")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="report_groups_list")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _student_menu_kb(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📈 Успеваемость", callback_data=f"stud_{user_id}_progress")],
        [InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"stud_{user_id}_edit")],
        [InlineKeyboardButton(text="🗑️ Удалить из списка", callback_data=f"stud_{user_id}_delete")],
        [InlineKeyboardButton(text="⬅️ Назад к списку", callback_data="students_back")],
    ])


@router.message(StateFilter('*'), lambda m: m.text == "📈 Успеваемость")
async def report_entry(message: types.Message, state: FSMContext):
    await state.clear()
    students = get_all_students()
    await state.update_data(report_students=students, report_query="", report_page=1)
    await message.answer("Выберите ученика:", reply_markup=_report_students_kb(students, page=1))


@router.callback_query(lambda c: c.data == "students_back")
async def students_back(cb: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    students = data.get("report_students") or get_all_students()
    page = int(data.get("report_page") or 1)
    try:
        await cb.message.edit_text("Выберите ученика:", reply_markup=_report_students_kb(students, page=page))
    except Exception:
        await cb.message.answer("Выберите ученика:", reply_markup=_report_students_kb(students, page=page))
    await cb.answer()


@router.callback_query(lambda c: c.data == "students_show_all")
async def students_show_all(cb: types.CallbackQuery, state: FSMContext):
    changed = clear_hide_reason_all()
    text = "Сброшены скрытия у всех учеников." if changed else "Никто не был скрыт."
    students = get_all_students()
    await state.update_data(report_students=students, report_query="", report_page=1)
    try:
        await cb.message.edit_text("Выберите ученика:", reply_markup=_report_students_kb(students, page=1))
    except Exception:
        await cb.message.answer("Выберите ученика:", reply_markup=_report_students_kb(students, page=1))
    await cb.answer(text, show_alert=True)


# ── Поиск ученика по имени/username ───────────────────────────────────────────

@router.callback_query(lambda c: c.data == "report_search")
async def report_search_start(cb: types.CallbackQuery, state: FSMContext):
    await state.set_state(ReportSearch.waiting_query)
    await cb.message.answer("Введите часть имени или username (можно с @):")
    await cb.answer()


@router.message(ReportSearch.waiting_query)
async def report_search_apply(m: types.Message, state: FSMContext):
    query = (m.text or "").strip()
    students = get_all_students()
    filtered = _filter_students(students, query)
    await state.update_data(report_students=filtered, report_query=query, report_page=1)
    kb = _report_students_kb(filtered, page=1)
    await state.clear()
    await m.answer("Результаты поиска:", reply_markup=kb)


@router.callback_query(lambda c: c.data and c.data.startswith("report_page:"))
async def report_students_page(cb: types.CallbackQuery, state: FSMContext):
    arg = cb.data.split(":", 1)[1]
    if arg == "noop":
        await cb.answer()
        return
    try:
        page = int(arg)
    except Exception:
        page = 1
    data = await state.get_data()
    students = data.get("report_students") or get_all_students()
    await state.update_data(report_page=page)
    try:
        await cb.message.edit_reply_markup(reply_markup=_report_students_kb(students, page=page))
    except Exception:
        try:
            await cb.message.edit_text("Выберите ученика:", reply_markup=_report_students_kb(students, page=page))
        except Exception:
            await cb.message.answer("Выберите ученика:", reply_markup=_report_students_kb(students, page=page))
    await cb.answer()


# ── Просмотр по группам (только для чтения) ───────────────────────────────────

@router.callback_query(lambda c: c.data == "report_groups_list")
async def report_groups_list(cb: types.CallbackQuery):
    groups = get_all_group_numbers()
    if not groups:
        await cb.answer("Группы не найдены", show_alert=True)
        return
    try:
        await cb.message.edit_text("Список групп:", reply_markup=_report_groups_kb(groups))
    except Exception:
        await cb.message.answer("Список групп:", reply_markup=_report_groups_kb(groups))
    await cb.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("rep_open_group:"))
async def report_open_group(cb: types.CallbackQuery):
    try:
        group_no = int(cb.data.split(":", 1)[1])
    except Exception:
        await cb.answer()
        return
    user_ids = get_work_group_members(group_no)
    if not user_ids:
        await cb.message.edit_text(f"В группе {group_no} пока нет участников.", reply_markup=_report_groups_kb(get_all_group_numbers()))
        await cb.answer()
        return
    students = get_all_students_with_plans()
    by_id = {int(s["user_id"]): s for s in students}
    members = [by_id.get(int(uid), {"user_id": uid, "label": f"ID {uid}"}) for uid in user_ids]
    try:
        await cb.message.edit_text(f"Участники группы {group_no}:", reply_markup=_report_group_members_kb(members))
    except Exception:
        await cb.message.answer(f"Участники группы {group_no}:", reply_markup=_report_group_members_kb(members))
    await cb.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("rep_open_student:"))
async def report_open_student(cb: types.CallbackQuery):
    try:
        user_id = int(cb.data.split(":", 1)[1])
    except Exception:
        await cb.answer()
        return
    # Показать мини-сводку и меню прогресса
    try:
        summary = build_user_summary_text(user_id)
        await cb.message.answer(summary, parse_mode="HTML", reply_markup=_progress_menu_kb(user_id))
    except Exception as e:
        await cb.message.answer(f"Не удалось сформировать сводку: {e}")
    await cb.answer()


@router.callback_query(lambda c: c.data == "rep_back_del")
async def rep_back_delete(cb: types.CallbackQuery, state: FSMContext):
    """Удаляет сообщение со статистикой и возвращает к меню ученика."""
    try:
        await cb.message.delete()
    except Exception:
        pass
    # Попробуем восстановить user_id из предыдущего контекста: часто предыдущее сообщение — меню ученика
    # Если восстановить не удастся — вернём список учеников
    data = await state.get_data()
    user_id = data.get("current_report_user_id")
    if user_id:
        try:
            await cb.message.answer(f"Ученик ID {int(user_id)}. Выберите действие:", reply_markup=_student_menu_kb(int(user_id)))
        except Exception:
            await cb.message.answer("Выберите ученика:", reply_markup=_report_students_kb(get_all_students(), page=1))
    else:
        await cb.message.answer("Выберите ученика:", reply_markup=_report_students_kb(get_all_students(), page=1))
    await cb.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("student_"))
async def student_selected(cb: types.CallbackQuery):
    try:
        user_id = int(cb.data.split("_", 1)[1])
    except Exception:
        await cb.answer("Ошибка ID", show_alert=True)
        return
    try:
        # Сохраним user_id для корректной работы кнопки "Назад" из статистики
        try:
            from aiogram.fsm.context import FSMContext  # type: ignore
        except Exception:
            FSMContext = None  # noqa: N806
        # Нельзя напрямую получить state здесь без DI, но меню ученика вызывается из состояний, где state доступен
        # Поэтому продублируем user_id в тексте и будем возвращаться к меню без обращения к state
        await cb.message.edit_text(f"Ученик ID {user_id}. Выберите действие:", reply_markup=_student_menu_kb(user_id))
    except Exception:
        await cb.message.answer(f"Ученик ID {user_id}. Выберите действие:", reply_markup=_student_menu_kb(user_id))
    await cb.answer()


def _progress_menu_kb(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 ЕГЭ", callback_data=f"prog_{user_id}_ege")],
        [InlineKeyboardButton(text="📊 ОГЭ", callback_data=f"prog_{user_id}_oge")],
        [InlineKeyboardButton(text="🗂 Карточки", callback_data=f"prog_{user_id}_cards")],
        [InlineKeyboardButton(text="🗣 Устный зачёт", callback_data=f"prog_{user_id}_oral")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="rep_back_del")],
    ])


def _back_delete_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="rep_back_del")]])


@router.callback_query(lambda c: c.data and c.data.endswith("_progress"))
async def student_progress(cb: types.CallbackQuery):
    user_id = int(cb.data.split("_", 2)[1])
    # Минимальная общая сводка + меню выбора типа статистики
    try:
        summary = build_user_summary_text(user_id)
        await cb.message.answer(summary, parse_mode="HTML", reply_markup=_progress_menu_kb(user_id))
    except Exception as e:
        await cb.message.answer(f"Не удалось сформировать сводку: {e}")
    await cb.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("prog_") and c.data.endswith("_ege"))
async def show_progress_ege(cb: types.CallbackQuery):
    user_id = int(cb.data.split("_", 2)[1])
    # Разделяем статистику: здесь считаем только по базе ЕГЭ
    text = build_user_progress_text_ege(user_id)
    await cb.message.answer("<b>Статистика по тестам ЕГЭ</b>\n\n" + text, parse_mode="HTML", reply_markup=_back_delete_kb())
    await cb.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("prog_") and c.data.endswith("_oge"))
async def show_progress_oge(cb: types.CallbackQuery):
    user_id = int(cb.data.split("_", 2)[1])
    # Статистика только по базе ОГЭ
    text = build_user_progress_text_oge(user_id)
    await cb.message.answer("<b>Статистика по тестам ОГЭ</b>\n\n" + text, parse_mode="HTML", reply_markup=_back_delete_kb())
    await cb.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("prog_") and c.data.endswith("_cards"))
async def show_progress_cards(cb: types.CallbackQuery):
    user_id = int(cb.data.split("_", 2)[1])
    text = build_user_flashcards_text(user_id)
    await cb.message.answer("<b>Статистика по карточкам</b>\n\n" + text, parse_mode="HTML", reply_markup=_back_delete_kb())
    await cb.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("prog_") and c.data.endswith("_oral"))
async def show_progress_oral(cb: types.CallbackQuery):
    user_id = int(cb.data.split("_", 2)[1])
    text = build_user_oral_text(user_id)
    await cb.message.answer("<b>Устный зачёт</b>\n\n" + text, parse_mode="HTML", reply_markup=_back_delete_kb())
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
    await m.answer("Username обновлён. Возвращаю список учеников...", reply_markup=_report_students_kb(get_all_students(), page=1))


@router.message(EditStudent.waiting_new_fullname)
async def save_new_fullname(m: types.Message, state: FSMContext):
    data = await state.get_data()
    user_id = int(data["edit_user_id"])  # кому меняем
    new_fullname = (m.text or "").strip()
    update_user_profile(user_id, full_name=new_fullname)
    await state.clear()
    await m.answer("Имя обновлено. Возвращаю список учеников...", reply_markup=_report_students_kb(get_all_students(), page=1))


@router.callback_query(lambda c: c.data and c.data.endswith("_delete"))
async def hide_student(cb: types.CallbackQuery):
    user_id = int(cb.data.split("_", 2)[1])
    set_hide_reason(user_id, reason="hidden_by_teacher")
    # Обновляем список
    try:
        await cb.message.edit_text("Выберите ученика:", reply_markup=_report_students_kb(get_all_students(), page=1))
    except Exception:
        await cb.message.answer("Выберите ученика:", reply_markup=_report_students_kb(get_all_students(), page=1))
    await cb.answer("Ученик скрыт из списка. Используйте 'Показать всех' чтобы вернуть.", show_alert=True)
