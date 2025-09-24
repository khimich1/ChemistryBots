from aiogram import Router, types
import re
from aiogram.filters import Command
from aiogram.exceptions import TelegramBadRequest
from keyboards import (
    get_teacher_keyboard,
    get_students_keyboard,
    get_manage_groups_keyboard,
    get_group_numbers_keyboard,
    get_group_pick_keyboard,
    get_group_members_keyboard,
    get_task_method_keyboard,
    get_task_types_keyboard,
    get_variant_list_keyboard,
    get_group_tasks_kb,
    get_exam_pick_keyboard,
    get_test_types_list_keyboard,
    get_type_ids_keyboard,
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
    create_group_task,
    list_group_tasks,
    delete_group_task,
    get_group_task_by_id,
    get_question_ids_by_filename,
    get_question_ids_by_type,
)
from aiogram.fsm.context import FSMContext
from states import StudentsList, WorkGroups
from services.pdf_export import render_questions_to_pdf

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
    # Покажем кнопки выбора группы
    try:
        await callback.message.edit_text("Выберите группу для отправки сообщения:", reply_markup=get_group_pick_keyboard(groups, prefix="pick_broadcast_group"))
    except Exception:
        await callback.message.answer("Выберите группу для отправки сообщения:", reply_markup=get_group_pick_keyboard(groups, prefix="pick_broadcast_group"))
    # Оставим старый способ ввода числа как резервный
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


@router.callback_query(lambda c: c.data.startswith("pick_broadcast_group:"))
async def pick_broadcast_group(cb: types.CallbackQuery, state: FSMContext):
    await cb.answer()
    try:
        group_no = int(cb.data.split(":", 1)[1])
    except Exception:
        return
    await state.update_data(broadcast_group=group_no)
    await _safe_edit_text(cb.message, f"Группа {group_no} выбрана. Введите текст сообщения, оно уйдёт всем участникам группы:")
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
    # Предложим выбрать группу кнопками для добавления ученика
    try:
        await callback.message.answer("Выберите группу, куда добавить ученика:", reply_markup=get_group_pick_keyboard(groups or [], prefix="pick_add_group"))
    except Exception:
        pass
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


@router.callback_query(lambda c: c.data.startswith("pick_add_group:"))
async def pick_add_group(cb: types.CallbackQuery, state: FSMContext):
    await cb.answer()
    try:
        group_no = int(cb.data.split(":", 1)[1])
    except Exception:
        return
    await state.update_data(group_no=group_no)
    await _safe_edit_text(cb.message, f"Группа {group_no} выбрана. Теперь отправьте username ученика с @ (например, @ivan_ivanov):")
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


@router.callback_query(lambda c: c.data == "wg_tasks_start")
async def wg_tasks_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    groups = get_all_group_numbers()
    if not groups:
        await callback.message.answer("Группы пока не созданы. Сначала добавьте участников.")
        return
    try:
        await callback.message.edit_text("Выберите группу, для которой создаём задания:", reply_markup=get_group_pick_keyboard(groups, prefix="pick_tasks_group"))
    except Exception:
        await callback.message.answer("Выберите группу, для которой создаём задания:", reply_markup=get_group_pick_keyboard(groups, prefix="pick_tasks_group"))
    await state.set_state(WorkGroups.waiting_tasks_group)


@router.message(WorkGroups.waiting_tasks_group)
async def wg_tasks_group(message: types.Message, state: FSMContext):
    try:
        group_no = int((message.text or "").strip())
    except ValueError:
        await message.answer("Пожалуйста, введите целое число (например, 1). Попробуйте ещё раз:")
        return
    await state.update_data(tasks_group=group_no)
    tasks = list_group_tasks(group_no)
    if tasks:
        try:
            await message.answer("У этой группы уже есть наборы:", reply_markup=get_group_tasks_kb(tasks))
        except Exception:
            # На случай, если редактирование/отправка с клавиатурой не удалось — покажем текстом и следом клавиатуру
            await message.answer("У этой группы уже есть наборы:")
            await message.answer("Выберите набор:", reply_markup=get_group_tasks_kb(tasks))
    await message.answer("Введите название набора (например, Домашка 24.09):")
    await state.set_state(WorkGroups.waiting_tasks_title)


@router.callback_query(lambda c: c.data.startswith("pick_tasks_group:"))
async def pick_tasks_group(cb: types.CallbackQuery, state: FSMContext):
    await cb.answer()
    try:
        group_no = int(cb.data.split(":", 1)[1])
    except Exception:
        return
    await state.update_data(tasks_group=group_no)
    # Показать уже имеющиеся наборы
    tasks = list_group_tasks(group_no)
    if tasks:
        try:
            await _safe_edit_text(cb.message, "У этой группы уже есть наборы:", reply_markup=get_group_tasks_kb(tasks))
        except Exception:
            await cb.message.answer("У этой группы уже есть наборы:", reply_markup=get_group_tasks_kb(tasks))
    await cb.message.answer("Введите название набора (например, Домашка 24.09):")
    await state.set_state(WorkGroups.waiting_tasks_title)


@router.message(WorkGroups.waiting_tasks_title)
async def wg_tasks_title(message: types.Message, state: FSMContext):
    title = (message.text or "").strip()
    if not title:
        await message.answer("Название не распознано, введите ещё раз:")
        return
    await state.update_data(tasks_title=title)
    await message.answer("Выберите базу:", reply_markup=get_exam_pick_keyboard())
    await state.set_state(WorkGroups.waiting_tasks_exam)


@router.message(WorkGroups.waiting_tasks_exam)
async def wg_tasks_exam(message: types.Message, state: FSMContext):
    # Если пользователь всё же напишет текстом, поддержим старый способ
    exam = (message.text or "").strip().lower()
    if exam in {"ege", "егэ", "oge", "огэ"}:
        canonical = "ege" if exam in {"ege", "егэ"} else "oge"
        await state.update_data(tasks_exam=canonical)
        await message.answer("Выберите способ добавления заданий:", reply_markup=get_task_method_keyboard(canonical))
        await state.set_state(WorkGroups.waiting_tasks_ids)
    else:
        await message.answer("Выберите базу:", reply_markup=get_exam_pick_keyboard())


@router.message(WorkGroups.waiting_tasks_ids)
async def wg_tasks_ids(message: types.Message, state: FSMContext):
    ids_text = (message.text or "").strip()
    if not ids_text:
        await message.answer("Пустой ввод. Примеры: 1, 5, 10  |  variant: test.pdf  |  types: 1=5, 2=3")
        return
    data = await state.get_data()
    group_no = int(data.get("tasks_group") or 0)
    title = data.get("tasks_title") or "Набор"
    exam = (data.get("tasks_exam") or "ege").lower()

    text_low = ids_text.lower()
    ids: list[int] = []

    # 1) Вариант по имени файла
    if text_low.startswith(("variant:", "вариант:", "filename:", "file:", "файл:")):
        filename = ids_text.split(":", 1)[1].strip() if ":" in ids_text else ""
        ids = get_question_ids_by_filename(exam, filename)
        if not ids:
            await message.answer("Не нашёл вопросы по такому имени файла. Проверьте 'variant: <filename>' и попробуйте снова.")
            return

    # 2) По типам и количеству
    elif text_low.startswith(("types:", "type:", "типы:", "виды:")):
        body = ids_text.split(":", 1)[1] if ":" in ids_text else ""
        pairs = [p for p in re.split(r"[;,]", body) if p.strip()]
        if not pairs:
            await message.answer("Не распознал пары типов. Пример: types: 1=5, 2=3")
            return
        max_type = 28 if exam == "ege" else 19
        collected: list[int] = []
        for pair in pairs:
            m = re.match(r"\s*(\d+)\s*[:=x×]\s*(\d+)\s*", pair)
            if not m:
                await message.answer("Неверный формат. Используйте: 1=5, 2=3")
                return
            t = int(m.group(1))
            cnt = int(m.group(2))
            if t < 1 or t > max_type or cnt < 1:
                await message.answer(f"Тип должен быть 1..{max_type}, количество > 0")
                return
            collected.extend(get_question_ids_by_type(exam, t, cnt))
        seen = set()
        ids = [x for x in collected if not (x in seen or seen.add(x))]
        if not ids:
            await message.answer("Не удалось подобрать вопросы по указанным типам.")
            return

    # 3) Список ID
    else:
        parts = [p.strip() for p in re.split(r"[;,\s]+", ids_text) if p.strip()]
        if not parts or not all(p.isdigit() for p in parts):
            await message.answer("Ожидаются только числа через запятую. Пример: 1, 5, 10")
            return
        ids = [int(p) for p in parts]

    # Сохраним в общем CSV формате ege:1, ege:5 ... или oge:...
    items = ", ".join(f"{exam}:{p}" for p in ids)
    create_group_task(group_no, title, items)
    ids_str = ", ".join(str(i) for i in ids)
    await message.answer(f"✅ Набор '{title}' сохранён для группы {group_no}. ({exam.upper()} IDs: {ids_str})")
    await state.set_state(None)


# ── Новые обработчики для кнопок выбора способа/типов/варианта ─────────────

@router.callback_query(lambda c: c.data.startswith("wg_tasks_method:"))
async def wg_tasks_method(cb: types.CallbackQuery, state: FSMContext):
    try:
        _, method, exam = cb.data.split(":", 2)
    except Exception:
        await cb.answer()
        return
    if method == "ids":
        await _safe_edit_text(cb.message, "Введите IDs через запятую (например: 1, 5, 10)")
        await cb.answer()
        return
    if method == "testlist":
        # Не сбрасываем уже выбранные ID, чтобы можно было возвращаться назад и добирать задания
        prev = await state.get_data()
        prev_selected = list(prev.get("ids_selected") or [])
        await state.update_data(tasks_exam=exam, ids_selected=prev_selected, ids_list=[], current_type=None, ids_page=1)
        await _safe_edit_text(cb.message, "Выбери тест:", reply_markup=get_test_types_list_keyboard(exam))
        await cb.answer()
        return


@router.callback_query(lambda c: c.data.startswith("wg_pick_type:"))
async def wg_pick_type(cb: types.CallbackQuery, state: FSMContext):
    try:
        _, exam, t_str, cnt_str = cb.data.split(":", 3)
        t = int(t_str)
        cnt = int(cnt_str)
    except Exception:
        await cb.answer()
        return
    data = await state.get_data()
    selected = dict(data.get("selected_types") or {})
    selected[t] = cnt
    await state.update_data(selected_types=selected, tasks_exam=exam)
    await cb.answer(f"Добавлено: {t}={cnt}")


@router.callback_query(lambda c: c.data == "wg_types_done")
async def wg_types_done(cb: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    exam = (data.get("tasks_exam") or "ege").lower()
    selected: dict = data.get("selected_types") or {}
    if not selected:
        await cb.answer("Список пуст", show_alert=True)
        return
    # Собираем ID по выбранным типам
    ids_collected: list[int] = []
    for t, cnt in selected.items():
        ids_collected.extend(get_question_ids_by_type(exam, int(t), int(cnt)))
    # Уникализируем
    seen = set()
    ids = [x for x in ids_collected if not (x in seen or seen.add(x))]
    if not ids:
        await cb.answer("Не удалось подобрать вопросы", show_alert=True)
        return
    group_no = int(data.get("tasks_group") or 0)
    title = data.get("tasks_title") or "Набор"
    items = ", ".join(f"{exam}:{p}" for p in ids)
    create_group_task(group_no, title, items)
    await cb.message.edit_text(f"✅ Набор '{title}' сохранён для группы {group_no}. ({exam.upper()} IDs: {', '.join(map(str, ids))})")
    await state.set_state(None)
    await cb.answer()


@router.callback_query(lambda c: c.data.startswith("wg_pick_exam:"))
async def wg_pick_exam(cb: types.CallbackQuery, state: FSMContext):
    canonical = (cb.data.split(":", 1)[1] or "ege").lower()
    if canonical not in {"ege", "oge"}:
        canonical = "ege"
    await state.update_data(tasks_exam=canonical)
    await _safe_edit_text(cb.message, "Выберите способ добавления заданий:", reply_markup=get_task_method_keyboard(canonical))
    await state.set_state(WorkGroups.waiting_tasks_ids)
    await cb.answer()


@router.callback_query(lambda c: c.data == "wg_types_back")
async def wg_types_back(cb: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    exam = (data.get("tasks_exam") or "ege").lower()
    await cb.message.edit_text("Выберите способ добавления заданий:", reply_markup=get_task_method_keyboard(exam))
    await cb.answer()


@router.callback_query(lambda c: c.data.startswith("wg_pick_test:"))
async def wg_pick_test(cb: types.CallbackQuery, state: FSMContext):
    try:
        _, exam, t_str = cb.data.split(":", 2)
        t = int(t_str)
    except Exception:
        await cb.answer()
        return
    ids = get_question_ids_by_type(exam, t, 200)
    # Не сбрасываем уже выбранные ids, чтобы можно было собирать набор из нескольких типов
    prev_data = await state.get_data()
    prev_selected = list(prev_data.get("ids_selected") or [])
    await state.update_data(tasks_exam=exam, current_type=t, ids_list=ids, ids_selected=prev_selected, ids_page=1)
    # Подсветим уже выбранные ID именно этого типа
    selected_for_current_type = {qid for qid in prev_selected if qid in ids}
    await _safe_edit_text(
        cb.message,
        "Выберите задания этого типа:",
        reply_markup=get_type_ids_keyboard(ids, exam=exam, task_type=t, selected=selected_for_current_type, page=1)
    )
    await cb.answer()


@router.callback_query(lambda c: c.data.startswith("wg_toggle_id:"))
async def wg_toggle_id(cb: types.CallbackQuery, state: FSMContext):
    try:
        _, exam, t_str, id_str, page_str = cb.data.split(":", 4)
        t = int(t_str)
        qid = int(id_str)
        page = int(page_str)
    except Exception:
        await cb.answer()
        return
    data = await state.get_data()
    ids_selected = set(data.get("ids_selected") or [])
    if qid in ids_selected:
        ids_selected.remove(qid)
    else:
        ids_selected.add(qid)
    ids_list = list(data.get("ids_list") or [])
    await state.update_data(ids_selected=list(ids_selected))
    try:
        await cb.message.edit_reply_markup(reply_markup=get_type_ids_keyboard(ids_list, exam=exam, task_type=t, selected=ids_selected, page=page))
    finally:
        await cb.answer()


@router.callback_query(lambda c: c.data.startswith("wg_ids_page:"))
async def wg_ids_page(cb: types.CallbackQuery, state: FSMContext):
    try:
        _, exam, t_str, page_str = cb.data.split(":", 3)
        t = int(t_str)
        page = int(page_str)
    except Exception:
        await cb.answer()
        return
    data = await state.get_data()
    ids_list = list(data.get("ids_list") or [])
    ids_selected = set(data.get("ids_selected") or [])
    await state.update_data(ids_page=page)
    try:
        await cb.message.edit_reply_markup(reply_markup=get_type_ids_keyboard(ids_list, exam=exam, task_type=t, selected=ids_selected, page=page))
    finally:
        await cb.answer()


@router.callback_query(lambda c: c.data == "wg_ids_done")
async def wg_ids_done(cb: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    exam = (data.get("tasks_exam") or "ege").lower()
    group_no = int(data.get("tasks_group") or 0)
    title = data.get("tasks_title") or "Набор"
    ids_selected = list(data.get("ids_selected") or [])
    if not ids_selected:
        await cb.answer("Ничего не выбрано", show_alert=True)
        return
    items = ", ".join(f"{exam}:{i}" for i in ids_selected)
    create_group_task(group_no, title, items)
    await cb.message.edit_text(f"✅ Набор '{title}' сохранён для группы {group_no}. ({exam.upper()} IDs: {', '.join(map(str, ids_selected))})")
    await state.set_state(None)
    await cb.answer()


@router.callback_query(lambda c: c.data == "wg_methods_back")
async def wg_methods_back(cb: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    exam = (data.get("tasks_exam") or "ege").lower()
    await _safe_edit_text(cb.message, "Выберите способ добавления заданий:", reply_markup=get_task_method_keyboard(exam))
    await cb.answer()


@router.callback_query(lambda c: c.data == "wg_ids_back")
async def wg_ids_back(cb: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    exam = (data.get("tasks_exam") or "ege").lower()
    await _safe_edit_text(cb.message, "Выбери тест:", reply_markup=get_test_types_list_keyboard(exam))
    await cb.answer()


@router.callback_query(lambda c: c.data.startswith("wg_task_del:"))
async def wg_task_delete(cb: types.CallbackQuery):
    """Удаляет набор заданий и обновляет список кнопок.
    Формат callback_data: wg_task_del:<task_id>
    """
    try:
        task_id = int(cb.data.split(":", 1)[1])
    except Exception:
        await cb.answer("Не понимаю id", show_alert=True)
        return
    group_no = delete_group_task(task_id)
    if group_no is None:
        await cb.answer("Набор не найден", show_alert=True)
        return
    tasks = list_group_tasks(group_no)
    try:
        # Обновим только клавиатуру у того же сообщения
        await cb.message.edit_reply_markup(reply_markup=get_group_tasks_kb(tasks))
    except Exception:
        # Если не получилось — отправим новое сообщение с клавиатурой
        await cb.message.answer("У этой группы уже есть наборы:", reply_markup=get_group_tasks_kb(tasks))
    await cb.answer("Удалено")


@router.callback_query(lambda c: c.data.startswith("wg_task_print:"))
async def wg_task_print(cb: types.CallbackQuery):
    """Генерирует PDF из выбранного набора заданий (по одному на лист)."""
    try:
        task_id = int(cb.data.split(":", 1)[1])
    except Exception:
        await cb.answer("Не понимаю id", show_alert=True)
        return
    task = get_group_task_by_id(task_id)
    if not task:
        await cb.answer("Набор не найден", show_alert=True)
        return
    # Разбираем items: "ege:1, oge:3, ege:5"
    items_raw = task.get("items") or ""
    pairs = [p.strip() for p in items_raw.split(",") if p.strip()]
    questions: list[dict] = []
    # Получаем тексты из соответствующих БД через helpers из services.groups
    from services.groups import _tests_db_path_for  # type: ignore
    import sqlite3
    for pair in pairs:
        try:
            exam, sid = pair.split(":", 1)
            qid = int(sid.strip())
            db_path = _tests_db_path_for(exam.strip().lower())
        except Exception:
            continue
        try:
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                # Подбор имён колонок
                def pick(colnames: list[str]) -> str | None:
                    try:
                        cur.execute("PRAGMA table_info(tests)")
                        cols = {r[1] for r in cur.fetchall()}
                    except Exception:
                        return None
                    for name in colnames:
                        if name in cols:
                            return name
                    return None
                q_col = pick(["question", "question_text", "text", "q_text"]) or "question"
                o_col = pick(["options", "variants", "choices", "answers"]) or None
                t_col = pick(["type", "test_type", "theme", "task_type"]) or None
                fields = [f"{q_col} AS question"]
                if o_col:
                    fields.append(f"{o_col} AS options")
                if t_col:
                    fields.append(f"{t_col} AS ttype")
                sql = f"SELECT {', '.join(fields)} FROM tests WHERE id=?"
                cur.execute(sql, (qid,))
                row = cur.fetchone()
                if row:
                    questions.append({
                        "title": f"Задание №{qid}",
                        "question": row["question"] if "question" in row.keys() else "",
                        "options": row["options"] if (o_col and "options" in row.keys()) else "",
                        "type": int(row["ttype"]) if (t_col and "ttype" in row.keys() and str(row["ttype"]).isdigit()) else None,
                        "exam": exam.strip().lower(),
                        "qid": qid,
                    })
        except Exception:
            continue
    if not questions:
        await cb.answer("Не удалось собрать задания", show_alert=True)
        return
    # Генерация PDF
    import tempfile, os
    tmp_dir = tempfile.mkdtemp(prefix="grp_pdf_")
    out_path = os.path.join(tmp_dir, f"group_set_{task_id}.pdf")
    pdf_path = render_questions_to_pdf(out_path, questions)
    # Отправляем файл
    try:
        from aiogram.types import FSInputFile
        await cb.message.answer_document(FSInputFile(pdf_path), caption=f"📄 {task.get('title')}")
    except Exception:
        await cb.answer("PDF создан, но не удалось отправить", show_alert=True)
        return
    await cb.answer("PDF готов")


@router.callback_query(lambda c: c.data.startswith("wg_task_open:"))
async def wg_task_open(cb: types.CallbackQuery):
    """Показывает состав набора: для каждого элемента выводит экзамен, тип и ID."""
    try:
        task_id = int(cb.data.split(":", 1)[1])
    except Exception:
        await cb.answer("Не понимаю id", show_alert=True)
        return
    task = get_group_task_by_id(task_id)
    if not task:
        await cb.answer("Набор не найден", show_alert=True)
        return
    # Разбираем items и достаём тип из БД соответствующего экзамена
    items_raw = task.get("items") or ""
    pairs = [p.strip() for p in items_raw.split(",") if p.strip()]
    lines: list[str] = []
    # Заголовок
    lines.append(f"Состав набора ‘{task.get('title') or task_id}’ (группа {task.get('group_no')}):")
    lines.append("<pre>")
    try:
        from services.groups import _tests_db_path_for  # type: ignore
        import sqlite3
        for pair in pairs:
            try:
                exam, sid = pair.split(":", 1)
                qid = int(sid.strip())
                db_path = _tests_db_path_for(exam.strip().lower())
            except Exception:
                continue
            ttype: int | None = None
            try:
                with sqlite3.connect(db_path) as conn:
                    cur = conn.cursor()
                    # Определим имя колонки типа
                    cur.execute("PRAGMA table_info(tests)")
                    cols = {r[1] for r in cur.fetchall()}
                    type_col = "type"
                    for name in ("type", "test_type", "theme", "task_type"):
                        if name in cols:
                            type_col = name
                            break
                    cur.execute(f"SELECT {type_col} FROM tests WHERE id=?", (qid,))
                    row = cur.fetchone()
                    if row and str(row[0]).isdigit():
                        ttype = int(row[0])
            except Exception:
                ttype = None
            exam_up = (exam or "").strip().upper()
            lines.append(f"{exam_up}: тип {ttype if ttype is not None else '?'}  •  id {qid}")
    except Exception:
        # Если что-то пошло не так — хотя бы отобразим id
        for pair in pairs:
            try:
                exam, sid = pair.split(":", 1)
                qid = int(sid.strip())
            except Exception:
                continue
            lines.append(f"{(exam or '').upper()}: id {qid}")
    lines.append("</pre>")
    # Кнопка назад к списку наборов этой группы
    kb = types.InlineKeyboardMarkup(
        inline_keyboard=[[types.InlineKeyboardButton(text="⬅️ Назад", callback_data=f"wg_tasks_list:{task.get('group_no')}")]]
    )
    await cb.message.edit_text("\n".join(lines), parse_mode="HTML", reply_markup=kb)
    await cb.answer()


@router.callback_query(lambda c: c.data.startswith("wg_tasks_list:"))
async def wg_tasks_list(cb: types.CallbackQuery):
    """Возвращает список наборов для указанной группы (после просмотра состава)."""
    try:
        group_no = int(cb.data.split(":", 1)[1])
    except Exception:
        await cb.answer()
        return
    tasks = list_group_tasks(group_no)
    try:
        await cb.message.edit_text("У этой группы уже есть наборы:", reply_markup=get_group_tasks_kb(tasks))
    except Exception:
        await cb.message.answer("У этой группы уже есть наборы:", reply_markup=get_group_tasks_kb(tasks))
    await cb.answer()


@router.callback_query(lambda c: c.data.startswith("wg_variants_page:"))
async def wg_variants_page(cb: types.CallbackQuery, state: FSMContext):
    try:
        arg = cb.data.split(":", 1)[1]
        if arg == "noop":
            await cb.answer()
            return
        page = int(arg)
    except Exception:
        page = 1
    data = await state.get_data()
    names = data.get("variants_list") or []
    await state.update_data(variants_page=page)
    await _safe_edit_text(cb.message, "Выберите вариант (filename):", reply_markup=get_variant_list_keyboard(names, page, 10))
    await cb.answer()


@router.callback_query(lambda c: c.data == "wg_variants_back")
async def wg_variants_back(cb: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    exam = (data.get("tasks_exam") or "ege").lower()
    await _safe_edit_text(cb.message, "Выберите способ добавления заданий:", reply_markup=get_task_method_keyboard(exam))
    await cb.answer()


@router.callback_query(lambda c: c.data.startswith("wg_pick_variant:"))
async def wg_pick_variant(cb: types.CallbackQuery, state: FSMContext):
    filename = cb.data.split(":", 1)[1]
    data = await state.get_data()
    exam = (data.get("tasks_exam") or "ege").lower()
    ids = get_question_ids_by_filename(exam, filename)
    if not ids:
        await cb.answer("Не нашёл вопросы по этому варианту", show_alert=True)
        return
    group_no = int(data.get("tasks_group") or 0)
    title = data.get("tasks_title") or f"Вариант {filename}"
    items = ", ".join(f"{exam}:{p}" for p in ids)
    create_group_task(group_no, title, items)
    await cb.message.edit_text(f"✅ Набор '{title}' сохранён для группы {group_no}. ({exam.upper()} IDs: {', '.join(map(str, ids))})")
    await state.set_state(None)
    await cb.answer()


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


async def _safe_edit_text(message_obj: types.Message, text: str, *, reply_markup=None) -> None:
    """Безопасно правит текст сообщения: если контент не меняется, тихо игнорирует ошибку.
    При иных ошибках отправляет новое сообщение."""
    try:
        await message_obj.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest:
        # message is not modified — просто игнорируем
        return
    except Exception:
        try:
            await message_obj.answer(text, reply_markup=reply_markup)
        except Exception:
            pass


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
