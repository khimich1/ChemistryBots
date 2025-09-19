from aiogram import Router, types
from aiogram.filters import Command
from keyboards import (
    get_teacher_keyboard,
    get_students_keyboard,
    get_manage_groups_keyboard,
    get_group_numbers_keyboard,
    get_group_members_keyboard,
)
from services.acquisition import get_ad_stats
from services.students import get_all_students
from services.teachers import get_teacher_moniker
from services.groups import (
    add_student_to_group,
    is_student_in_group,
    get_all_students_with_plans,
    add_user_to_work_group,
    find_user_id_by_username,
    get_all_group_numbers,
    get_work_group_members,
    broadcast_message_to_group_via_govr,
)
from aiogram.fsm.context import FSMContext
from states import StudentsList, WorkGroups

router = Router()

@router.message(Command("start"))
async def cmd_start(message: types.Message):
    tg_id = message.from_user.id
    moniker = get_teacher_moniker(tg_id) or (message.from_user.full_name or "")
    greeting_name = moniker.strip() or "Коллега"
    await message.answer(
        f"Здравствуйте, {greeting_name}! Выберите действие:",
        reply_markup=get_teacher_keyboard()
    )


@router.message(lambda m: m.text == "👥 Добавить в группу")
async def show_students_list(message: types.Message, state: FSMContext):
    """Показывает список всех зарегистрированных учеников"""
    students = get_all_students_with_plans()
    
    if not students:
        await message.answer("Пока нет зарегистрированных учеников.")
        return
    
    # Добавляем информацию о том, кто уже в группе
    for student in students:
        student["is_in_group"] = is_student_in_group(student["user_id"])

    # Сохраняем исходный список в FSM (для фильтров/поиска)
    await state.update_data(
        students=students,
        only_not_in_group=False,
        search_query="",
    )

    keyboard = get_students_keyboard(students, page=1, page_size=30, show_plans=True, has_search=False, only_not_in_group=False)
    await message.answer(
        "Список всех зарегистрированных учеников:\n\n"
        "Нажмите на ученика, чтобы добавить его в группу для доступа к тарифу 'Групповые':",
        reply_markup=keyboard
    )


@router.message(lambda m: m.text == "✅ Ученики в группе")
async def show_group_students(message: types.Message, state: FSMContext):
    """Показывает список только тех учеников, кто уже в группе"""
    students = get_all_students_with_plans()

    # Отметим статус и отфильтруем
    for s in students:
        s["is_in_group"] = is_student_in_group(s["user_id"])
    students = [s for s in students if s.get("is_in_group")]

    if not students:
        await message.answer("Пока в группе никого нет.")
        return

    await state.update_data(
        students=students,
        only_not_in_group=False,
        search_query="",
    )

    keyboard = get_students_keyboard(
        students, page=1, page_size=30,
        show_plans=True,
        has_search=False,
        only_not_in_group=False,
        show_controls=True,
        show_only_not_in_group_toggle=False,
    )
    await message.answer(
        "Ученики, которые уже в группе. Листайте страницы ⬅️➡️ или используйте поиск.",
        reply_markup=keyboard,
    )


@router.message(lambda m: m.text == "📚 Управление группами")
async def manage_groups_menu(message: types.Message):
    await message.answer("Выберите действие:", reply_markup=get_manage_groups_keyboard())


@router.callback_query(lambda c: c.data == "manage_groups_back")
async def manage_groups_back(callback: types.CallbackQuery):
    await callback.answer()
    await callback.message.edit_text("Выберите действие:", reply_markup=get_manage_groups_keyboard())


@router.callback_query(lambda c: c.data == "wg_broadcast_start")
async def wg_broadcast_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    groups = get_all_group_numbers()
    if not groups:
        await callback.message.answer("Группы пока не созданы. Сначала добавьте участников.")
        return
    await callback.message.answer("Введите номер группы, куда отправить сообщение:")
    await state.set_state(WorkGroups.waiting_broadcast_group)


@router.message(WorkGroups.waiting_broadcast_group)
async def wg_broadcast_group(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    try:
        group_no = int(text)
    except ValueError:
        await message.answer("Пожалуйста, введите целое число (например, 101). Попробуйте ещё раз:")
        return
    await state.update_data(broadcast_group=group_no)
    await message.answer("Введите текст сообщения, оно уйдёт всем участникам группы:")
    await state.set_state(WorkGroups.waiting_broadcast_text)


@router.message(WorkGroups.waiting_broadcast_text)
async def wg_broadcast_text(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    if not text:
        await message.answer("Текст пуст. Отправьте текст сообщения:")
        return
    data = await state.get_data()
    group_no = int(data.get("broadcast_group") or 0)
    user_ids = get_work_group_members(group_no)
    if not user_ids:
        await message.answer(f"В группе {group_no} нет участников.")
        await state.set_state(None)
        return
    ok, fail = await broadcast_message_to_group_via_govr(group_no, text)
    await message.answer(f"Отправлено: {ok}. Ошибок: {fail}.")
    await state.set_state(None)


@router.callback_query(lambda c: c.data == "wg_add_start")
async def wg_add_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    # Покажем список существующих групп, если есть
    groups = get_all_group_numbers()
    if groups:
        try:
            await callback.message.edit_text("Существующие группы:", reply_markup=get_group_numbers_keyboard(groups))
        except Exception:
            await callback.message.answer("Существующие группы:", reply_markup=get_group_numbers_keyboard(groups))
    await callback.message.answer("Введите номер группы (целое число):")
    await state.set_state(WorkGroups.waiting_group_number)


@router.message(WorkGroups.waiting_group_number)
async def wg_input_group(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    try:
        group_no = int(text)
    except ValueError:
        await message.answer("Пожалуйста, введите целое число (например, 101). Попробуйте ещё раз:")
        return
    await state.update_data(group_no=group_no)
    await message.answer("Теперь отправьте username ученика с @ (например, @ivan_ivanov):")
    await state.set_state(WorkGroups.waiting_username)


@router.message(WorkGroups.waiting_username)
async def wg_input_username(message: types.Message, state: FSMContext):
    username = (message.text or "").strip()
    if not username:
        await message.answer("Username не распознан. Отправьте в формате @username:")
        return
    data = await state.get_data()
    group_no = int(data.get("group_no") or 0)

    user_id = find_user_id_by_username(username)
    if not user_id:
        await message.answer("Не нашли такого пользователя в базе. Попросите его написать боту, затем повторите.")
        await state.set_state(None)
        return

    add_user_to_work_group(group_no, user_id)
    await message.answer(f"✅ Пользователь {username} (id={user_id}) добавлен в рабочую группу {group_no}.")
    await state.set_state(None)


@router.callback_query(lambda c: c.data == "manage_groups_list")
async def manage_groups_list(callback: types.CallbackQuery):
    await callback.answer()
    groups = get_all_group_numbers()
    if not groups:
        await callback.message.edit_text("Группы пока не созданы. Нажмите '➕ Добрать в рабочие группы' чтобы начать.", reply_markup=get_manage_groups_keyboard())
        return
    try:
        await callback.message.edit_text("Список групп:", reply_markup=get_group_numbers_keyboard(groups))
    except Exception:
        await callback.message.answer("Список групп:", reply_markup=get_group_numbers_keyboard(groups))


@router.callback_query(lambda c: c.data.startswith("wg_open:"))
async def wg_open_group(callback: types.CallbackQuery):
    await callback.answer()
    try:
        group_no = int(callback.data.split(":")[1])
    except Exception:
        group_no = 0
    user_ids = get_work_group_members(group_no)
    if not user_ids:
        await callback.message.edit_text(f"В группе {group_no} пока нет участников.", reply_markup=get_manage_groups_keyboard())
        return
    # Обогатим данными (label)
    students = get_all_students_with_plans()
    by_id = {s["user_id"]: s for s in students}
    members = [by_id.get(uid, {"user_id": uid, "label": f"ID {uid}"}) for uid in user_ids]
    try:
        await callback.message.edit_text(f"Участники группы {group_no}:", reply_markup=get_group_members_keyboard(members))
    except Exception:
        await callback.message.answer(f"Участники группы {group_no}:", reply_markup=get_group_members_keyboard(members))


@router.callback_query(lambda c: c.data.startswith("add_to_group:"))
async def add_student_to_group_handler(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик добавления ученика в группу"""
    try:
        parts = callback.data.split(":")
        # Форматы: add_to_group:<user_id> или add_to_group:<user_id>:<page>
        user_id = int(parts[1])
        page = int(parts[2]) if len(parts) >= 3 else 1
        
        # Получаем информацию об ученике
        data = await state.get_data()
        students = data.get("students") or get_all_students_with_plans()
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

        # Обновляем список учеников и клавиатуру на той же странице
        # Обновляем кэш: заново достанем с тарифами и отметим группу
        students = get_all_students_with_plans()
        for s in students:
            s["is_in_group"] = is_student_in_group(s["user_id"])
        # Применим текущие фильтры/поиск
        only_not_in_group = bool((await state.get_data()).get("only_not_in_group"))
        search_query = (await state.get_data()).get("search_query") or ""

        filtered = _apply_students_filters(students, only_not_in_group=only_not_in_group, search_query=search_query)
        await state.update_data(students=students)
        keyboard = get_students_keyboard(
            filtered, page=page, page_size=30,
            show_plans=True,
            has_search=bool(search_query.strip()),
            only_not_in_group=only_not_in_group,
        )
        try:
            await callback.message.edit_reply_markup(reply_markup=keyboard)
        except Exception:
            # Если не удалось отредактировать (например, старое сообщение), отправим новое
            await callback.message.answer(
                "Список всех зарегистрированных учеников:\n\n"
                "Нажмите на ученика, чтобы добавить его в группу для доступа к тарифу 'Групповые':",
                reply_markup=keyboard
            )
        
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


@router.callback_query(lambda c: c.data.startswith("students_page:"))
async def students_page_handler(callback: types.CallbackQuery, state: FSMContext):
    """Переключение страниц списка учеников"""
    try:
        arg = callback.data.split(":")[1]
        if arg == "noop":
            await callback.answer()
            return
        page = int(arg)
    except Exception:
        page = 1

    data = await state.get_data()
    students = data.get("students") or get_all_students_with_plans()
    if not students:
        await callback.answer("Список пуст", show_alert=True)
        return

    for s in students:
        s["is_in_group"] = is_student_in_group(s["user_id"])

    only_not_in_group = bool(data.get("only_not_in_group"))
    search_query = data.get("search_query") or ""
    filtered = _apply_students_filters(students, only_not_in_group=only_not_in_group, search_query=search_query)
    keyboard = get_students_keyboard(
        filtered, page=page, page_size=30,
        show_plans=True,
        has_search=bool(search_query.strip()),
        only_not_in_group=only_not_in_group,
    )
    try:
        await callback.message.edit_reply_markup(reply_markup=keyboard)
    finally:
        # Гасим загрузку
        await callback.answer()


def _apply_students_filters(students: list, *, only_not_in_group: bool, search_query: str) -> list:
    sq_raw = (search_query or "").strip().lower()
    # Поддерживаем ввод с @ и без @
    sq_no_at = sq_raw[1:] if sq_raw.startswith("@") else sq_raw
    query_variants = {sq_raw, sq_no_at}
    out = []
    for s in students:
        if only_not_in_group and s.get("is_in_group"):
            continue
        if sq_raw:
            label = (s.get("label") or "").lower()
            username = (s.get("username") or "").lower()
            username_no_at = username[1:] if username.startswith("@") else username
            full_name = (s.get("full_name") or "").lower()
            # Совпадение по любой из форм запроса
            if not any(q in label or q in username or q in username_no_at or q in full_name for q in query_variants):
                continue
        out.append(s)
    return out


@router.callback_query(lambda c: c.data == "students_search")
async def students_start_search(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.answer("Введите часть имени или username для поиска (или отправьте пусто, чтобы сбросить):")
    await state.set_state(StudentsList.waiting_search_query)


@router.message(StudentsList.waiting_search_query)
async def students_apply_search(message: types.Message, state: FSMContext):
    query = (message.text or "").strip()
    data = await state.get_data()
    students = data.get("students") or get_all_students_with_plans()

    for s in students:
        s["is_in_group"] = is_student_in_group(s["user_id"])

    only_not_in_group = bool(data.get("only_not_in_group"))
    filtered = _apply_students_filters(students, only_not_in_group=only_not_in_group, search_query=query)
    await state.update_data(search_query=query, students=students)

    keyboard = get_students_keyboard(
        filtered, page=1, page_size=30,
        show_plans=True,
        has_search=bool(query),
        only_not_in_group=only_not_in_group,
    )
    await message.answer(
        "Результаты поиска. Листайте страницы ⬅️➡️ или сбросьте фильтры.",
        reply_markup=keyboard,
    )
    await state.set_state(None)


@router.callback_query(lambda c: c.data == "students_toggle_filter")
async def students_toggle_only_not_in_group(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    students = data.get("students") or get_all_students_with_plans()
    only_not_in_group = not bool(data.get("only_not_in_group"))
    search_query = data.get("search_query") or ""

    for s in students:
        s["is_in_group"] = is_student_in_group(s["user_id"])

    filtered = _apply_students_filters(students, only_not_in_group=only_not_in_group, search_query=search_query)
    await state.update_data(only_not_in_group=only_not_in_group, students=students)

    keyboard = get_students_keyboard(
        filtered, page=1, page_size=30,
        show_plans=True,
        has_search=bool(search_query.strip()),
        only_not_in_group=only_not_in_group,
    )
    try:
        await callback.message.edit_reply_markup(reply_markup=keyboard)
    finally:
        await callback.answer()


@router.callback_query(lambda c: c.data == "students_clear")
async def students_clear_filters(callback: types.CallbackQuery, state: FSMContext):
    students = get_all_students_with_plans()
    for s in students:
        s["is_in_group"] = is_student_in_group(s["user_id"])
    await state.update_data(students=students, search_query="", only_not_in_group=False)

    keyboard = get_students_keyboard(
        students, page=1, page_size=30,
        show_plans=True,
        has_search=False,
        only_not_in_group=False,
    )
    try:
        await callback.message.edit_reply_markup(reply_markup=keyboard)
    finally:
        await callback.answer()


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
