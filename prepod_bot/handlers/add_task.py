from aiogram import Router, types
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import StateFilter

from keyboards import get_manage_tasks_keyboard, get_teacher_keyboard
from services.tasks import (
    list_problem_tasks,
    get_task_by_id,
    update_task_field,
    unhide_task,
)
<<<<<<< Updated upstream
from states import EditTask
=======
from services.teacher_tests import (
    save_image,
    add_teacher_task,
    list_task_sets,
    create_task_set,
    list_tasks_in_set,
    get_task_set_by_id,
    count_tasks_in_set,
    delete_task_set,
    compute_teacher_set_results,
)
from states import EditTask, AddTeacherTask
>>>>>>> Stashed changes
from utils.message_manager import message_manager

router = Router()

@router.message(StateFilter('*'), lambda m: m.text == "🛠 Управление заданиями")
async def manage_tasks_menu(message: types.Message, state: FSMContext):
    await state.clear()
    await message_manager.delete_user_messages_fast(message.bot, message.from_user.id, message.chat.id)
    sent = await message.answer("Выберите действие:", reply_markup=get_manage_tasks_keyboard())
    try:
        message_manager.add_message(message.from_user.id, sent.message_id)
    except Exception:
        pass


@router.message(StateFilter('*'), lambda m: m.text == "⬅️ Назад")
async def manage_back(message: types.Message, state: FSMContext):
    await state.clear()
    await message_manager.delete_user_messages_fast(message.bot, message.from_user.id, message.chat.id)
    sent = await message.answer("Главное меню:", reply_markup=get_teacher_keyboard())
    try:
        message_manager.add_message(message.from_user.id, sent.message_id)
    except Exception:
        pass


def _sets_list_kb() -> InlineKeyboardMarkup:
    sets = list_task_sets()
    rows: list[list[InlineKeyboardButton]] = []
    for s in sets:
        title = s.get("title") or f"Набор {s.get('id')}"
        if len(title) > 40:
            title = title[:37] + "…"
        sid = s.get("id")
        open_btn = InlineKeyboardButton(text=title, callback_data=f"tt_set_open:{sid}")
        stats_btn = InlineKeyboardButton(text="📊", callback_data=f"tt_stats:{sid}")
        print_btn = InlineKeyboardButton(text="🖨", callback_data=f"tt_print:{sid}")
        del_btn = InlineKeyboardButton(text="🗑", callback_data=f"tt_delete:{sid}")
        rows.append([open_btn, stats_btn, print_btn, del_btn])
    rows.append([InlineKeyboardButton(text="➕ Создать задание", callback_data="tt_set_create")])
    rows.append([InlineKeyboardButton(text="⬅️ В главное меню", callback_data="tt_back_main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(lambda m: m.text == "➕ Добавить")
<<<<<<< Updated upstream
async def manage_add_placeholder(message: types.Message):
    sent = await message.answer("Функция добавления появится позже.")
=======
async def manage_add_start(message: types.Message, state: FSMContext):
    await state.clear()
    # При первом входе показываем список наборов построчно: название + 📊 + 🖨 + 🗑
    kb = _sets_list_kb()
    sent = await message.answer("Выберите набор или создайте новый:", reply_markup=kb)
    try:
        message_manager.add_message(message.from_user.id, sent.message_id)
    except Exception:
        pass


@router.message(AddTeacherTask.waiting_question_and_image)
async def on_question_and_image(message: types.Message, state: FSMContext):
    # Позволяем вернуться назад клавишей
    if message.text == "⬅️ Назад":
        await state.clear()
        await message_manager.delete_user_messages_fast(message.bot, message.from_user.id, message.chat.id)
        sent = await message.answer("Выберите действие:", reply_markup=get_manage_tasks_keyboard())
        try:
            message_manager.add_message(message.from_user.id, sent.message_id)
        except Exception:
            pass
        return

    text = (message.caption or message.text or "").strip()
    image_id: int | None = None
    # Если прислано фото — сохраняем максимальное по размеру
    if message.photo:
        try:
            photo = message.photo[-1]
            file = await message.bot.get_file(photo.file_id)
            file_bytes = await message.bot.download_file(file.file_path)
            data = file_bytes.read()
            image_id = save_image(filename=f"tg_{photo.file_unique_id}.jpg", mime_type="image/jpeg", data=data)
        except Exception:
            image_id = None

    if not text and image_id is None:
        sent = await message.answer("Отправьте текст и/или фото задания (можно одно из двух).")
        try:
            message_manager.add_message(message.from_user.id, sent.message_id)
        except Exception:
            pass
        return

    await state.update_data(add_question=text, add_image_id=image_id)
    await state.set_state(AddTeacherTask.waiting_correct_answer)
    sent = await message.answer("Теперь пришлите номер правильного ответа (число).", reply_markup=get_manage_tasks_keyboard())
    try:
        message_manager.add_message(message.from_user.id, sent.message_id)
    except Exception:
        pass


@router.message(AddTeacherTask.waiting_correct_answer)
async def on_correct_answer(message: types.Message, state: FSMContext):
    if message.text == "⬅️ Назад":
        # Вернёмся на этап ввода вопроса
        await state.set_state(AddTeacherTask.waiting_question_and_image)
        sent = await message.answer("Отправьте текст задания и опционально фото.")
        try:
            message_manager.add_message(message.from_user.id, sent.message_id)
        except Exception:
            pass
        return

    raw = (message.text or "").strip()
    if not raw.isdigit():
        sent = await message.answer("Ожидаю число. Пришлите только номер правильного варианта, например: 3")
        try:
            message_manager.add_message(message.from_user.id, sent.message_id)
        except Exception:
            pass
        return

    data = await state.get_data()
    q_text = data.get("add_question") or ""
    image_id = data.get("add_image_id")
    # teacher id = message.from_user.id
    set_id = (await state.get_data()).get("current_set_id")
    new_id = add_teacher_task(
        teacher_tg_id=message.from_user.id,
        question_text=q_text,
        image_id=int(image_id) if (image_id is not None) else None,
        correct_answer=raw,
        set_id=int(set_id) if set_id else None,
    )
    # После добавления показываем мини-меню: «➕ Добавить ещё» и «✅ Закончить»
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить ещё в этот набор", callback_data=f"tt_add_more:{set_id or 0}")],
        [InlineKeyboardButton(text="✅ Закончить", callback_data="tt_finish")],
    ])
    sent = await message.answer(f"✅ Задание сохранено (id={new_id}). Что дальше?", reply_markup=kb)
>>>>>>> Stashed changes
    try:
        message_manager.add_message(message.from_user.id, sent.message_id)
    except Exception:
        pass


@router.message(lambda m: m.text == "🛠 Исправить")
async def manage_fix_list(message: types.Message):
    tasks = list_problem_tasks()
    if not tasks:
        sent = await message.answer("Нет скрытых заданий.")
        try:
            message_manager.add_message(message.from_user.id, sent.message_id)
        except Exception:
            pass
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"#{t['id']} • {t['question'][:32]}…", callback_data=f"dbg_task_{t['id']}")]
        for t in tasks
    ])
    sent = await message.answer("Выберите задание для правки:", reply_markup=kb)
    try:
        message_manager.add_message(message.from_user.id, sent.message_id)
    except Exception:
        pass


def _edit_task_kb(task_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Редактировать текст задания", callback_data=f"dbg_edit_q_{task_id}")],
        [InlineKeyboardButton(text="✏️ Редактировать варианты", callback_data=f"dbg_edit_opts_{task_id}")],
        [InlineKeyboardButton(text="✏️ Редактировать верный ответ", callback_data=f"dbg_edit_ans_{task_id}")],
        [InlineKeyboardButton(text="✏️ Редактировать подсказку", callback_data=f"dbg_edit_hint_{task_id}")],
        [InlineKeyboardButton(text="⬅️ К списку", callback_data="dbg_back")],
        [InlineKeyboardButton(text="✅ Отображать вновь", callback_data=f"dbg_unhide_{task_id}")],
    ])


@router.callback_query(lambda c: c.data and c.data.startswith("dbg_task_"))
async def open_task(cb: types.CallbackQuery):
    task_id = int(cb.data.split("_")[-1])
    task = get_task_by_id(task_id)
    if not task:
        await cb.answer("Задание не найдено", show_alert=True)
        return
    text = (
        f"Задание #{task['id']}\n\n"
        f"{task['question']}\n\n"
        f"Варианты:\n{task['options']}\n\n"
        f"Верный ответ: {task['correct_answer']}\n\n"
        f"Подсказка: {task.get('hint','')}"
    )
    try:
        await cb.message.edit_text(text)
        await cb.message.edit_reply_markup(reply_markup=_edit_task_kb(task_id))
    except Exception:
        sent = await cb.message.answer(text, reply_markup=_edit_task_kb(task_id))
        try:
            message_manager.add_message(cb.from_user.id, sent.message_id)
        except Exception:
            pass
    await cb.answer()


@router.callback_query(lambda c: c.data == "dbg_back")
async def back_to_list(cb: types.CallbackQuery):
    tasks = list_problem_tasks()
    if not tasks:
        try:
            await cb.message.edit_text("Нет скрытых заданий.")
        except Exception:
            sent = await cb.message.answer("Нет скрытых заданий.")
            try:
                message_manager.add_message(cb.from_user.id, sent.message_id)
            except Exception:
                pass
        await cb.answer()
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"#{t['id']} • {t['question'][:32]}…", callback_data=f"dbg_task_{t['id']}")]
        for t in tasks
    ])
    try:
        await cb.message.edit_text("Выберите задание для правки:")
        await cb.message.edit_reply_markup(reply_markup=kb)
    except Exception:
        sent = await cb.message.answer("Выберите задание для правки:", reply_markup=kb)
        try:
            message_manager.add_message(cb.from_user.id, sent.message_id)
        except Exception:
            pass
    await cb.answer()


@router.callback_query(lambda c: c.data and (c.data.startswith("dbg_edit_q_") or c.data.startswith("dbg_edit_opts_") or c.data.startswith("dbg_edit_ans_") or c.data.startswith("dbg_edit_hint_")))
async def ask_new_text(cb: types.CallbackQuery, state: FSMContext):
    data = cb.data
    if data.startswith("dbg_edit_q_"):
        field = "question"
    elif data.startswith("dbg_edit_opts_"):
        field = "options"
    elif data.startswith("dbg_edit_ans_"):
        field = "correct_answer"
    else:
        field = "hint"
    task_id = int(data.split("_")[-1])
    await state.set_state(EditTask.waiting_new_text)
    await state.update_data(edit_task_id=task_id, edit_field=field)
    sent = await cb.message.answer("Пришлите новый текст:")
    try:
        message_manager.add_message(cb.from_user.id, sent.message_id)
    except Exception:
        pass
    await cb.answer()


@router.message(EditTask.waiting_new_text)
async def save_new_text(m: types.Message, state: FSMContext):
    data = await state.get_data()
    task_id = int(data["edit_task_id"])
    field = data["edit_field"]
    new_text = (m.text or "").strip()
    update_task_field(task_id, field, new_text)
    await state.clear()
    # Перепокажем карточку задания
    task = get_task_by_id(task_id)
    text = (
        f"Задание #{task['id']}\n\n"
        f"{task['question']}\n\n"
        f"Варианты:\n{task['options']}\n\n"
        f"Верный ответ: {task['correct_answer']}\n\n"
        f"Подсказка: {task.get('hint','')}"
    )
    sent1 = await m.answer("Изменения сохранены.")
    sent2 = await m.answer(text, reply_markup=_edit_task_kb(task_id))
    try:
        message_manager.add_message(m.from_user.id, sent1.message_id)
        message_manager.add_message(m.from_user.id, sent2.message_id)
    except Exception:
        pass


@router.callback_query(lambda c: c.data and c.data.startswith("dbg_unhide_"))
async def unhide_and_back(cb: types.CallbackQuery):
    task_id = int(cb.data.split("_")[-1])
    unhide_task(task_id)
    # Покажем обновлённый список
    tasks = list_problem_tasks()
    if not tasks:
        try:
            await cb.message.edit_text("Готово. Все исправлено, скрытых заданий нет.")
        except Exception:
            sent = await cb.message.answer("Готово. Все исправлено, скрытых заданий нет.")
            try:
                message_manager.add_message(cb.from_user.id, sent.message_id)
            except Exception:
                pass
        await cb.answer()
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"#{t['id']} • {t['question'][:32]}…", callback_data=f"dbg_task_{t['id']}")]
        for t in tasks
    ])
    try:
        await cb.message.edit_text("Задание возвращено в выдачу. Выберите следующее:")
        await cb.message.edit_reply_markup(reply_markup=kb)
    except Exception:
        sent = await cb.message.answer("Задание возвращено в выдачу. Выберите следующее:", reply_markup=kb)
        try:
            message_manager.add_message(cb.from_user.id, sent.message_id)
        except Exception:
            pass
    await cb.answer()


# ── Новый раздел: управление наборами «Добавить» ─────────────────────────────────────

@router.callback_query(lambda c: c.data == "tt_back_main")
async def tt_back_main(cb: types.CallbackQuery):
    await cb.answer()
    try:
        await cb.message.edit_text("Главное меню:")
        await cb.message.edit_reply_markup(reply_markup=get_teacher_keyboard())
    except Exception:
        await cb.message.answer("Главное меню:", reply_markup=get_teacher_keyboard())


@router.callback_query(lambda c: c.data == "tt_set_create")
async def tt_set_create(cb: types.CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.set_state(AddTeacherTask.waiting_set_title)
    await cb.message.answer("Введите название задания (набора):")


@router.message(StateFilter(AddTeacherTask.waiting_set_title))
async def tt_receive_set_title(message: types.Message, state: FSMContext):
    title = (message.text or "").strip()
    if not title:
        await message.answer("Название пустое. Введите название ещё раз:")
        return
    set_id = create_task_set(title)
    await state.update_data(current_set_id=set_id)
    # Теперь переходим к добавлению первого вопроса
    await state.set_state(AddTeacherTask.waiting_question_and_image)
    await message.answer(
        "Отправьте текст и/или фото первого задания (одно сообщение).",
        reply_markup=get_manage_tasks_keyboard(),
    )


@router.callback_query(lambda c: c.data.startswith("tt_set_open:"))
async def tt_set_open(cb: types.CallbackQuery, state: FSMContext):
    await cb.answer()
    try:
        set_id = int(cb.data.split(":", 1)[1])
    except Exception:
        return
    await state.update_data(current_set_id=set_id)
    info = get_task_set_by_id(set_id) or {"title": f"Набор {set_id}"}
    tasks = list_tasks_in_set(set_id)
    header = f"📋 {info.get('title')}\nВсего вопросов: {count_tasks_in_set(set_id)}"
    rows: list[list[InlineKeyboardButton]] = []
    for t in tasks[:20]:
        txt = (t.get("question") or "").strip()
        if len(txt) > 40:
            txt = txt[:37] + "…"
        rows.append([InlineKeyboardButton(text=f"#{t.get('id')} • {txt}", callback_data="noop")])
    # Кнопка добавления сразу запускает добавление в текущий набор
    rows.append([InlineKeyboardButton(text="➕ Добавить ещё", callback_data=f"tt_add_more:{set_id}")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="tt_sets_back")])
    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    try:
        await cb.message.edit_text(header)
        await cb.message.edit_reply_markup(reply_markup=kb)
    except Exception:
        await cb.message.answer(header, reply_markup=kb)


@router.callback_query(lambda c: c.data == "tt_sets_back")
async def tt_sets_back(cb: types.CallbackQuery, state: FSMContext):
    await cb.answer()
    try:
        # Если в состоянии запомнен текущий набор — покажем к нему кнопки 📊🖨🗑
        data = await state.get_data()
        current_set_id = data.get("current_set_id")
        await cb.message.edit_text("Выберите набор или создайте новый:")
        await cb.message.edit_reply_markup(reply_markup=_sets_list_kb())
    except Exception:
        await cb.message.answer("Выберите набор или создайте новый:", reply_markup=_sets_list_kb())


@router.callback_query(lambda c: c.data.startswith("tt_add_choose:"))
async def tt_add_choose(cb: types.CallbackQuery, state: FSMContext):
    await cb.answer()
    try:
        set_id = int(cb.data.split(":", 1)[1])
    except Exception:
        set_id = None
    if set_id:
        await state.update_data(current_set_id=set_id)
    # Показываем выбор набора (как на второй картинке) + ряд 📊🖨🗑 для текущего набора
    try:
        await cb.message.edit_text("Выберите набор или создайте новый:")
        await cb.message.edit_reply_markup(reply_markup=_sets_list_kb())
    except Exception:
        await cb.message.answer("Выберите набор или создайте новый:", reply_markup=_sets_list_kb())


@router.callback_query(lambda c: c.data.startswith("tt_add_more:"))
async def tt_add_more(cb: types.CallbackQuery, state: FSMContext):
    # Старое поведение: сразу перейти к добавлению в текущий набор
    await cb.answer()
    try:
        set_id = int(cb.data.split(":", 1)[1])
    except Exception:
        set_id = None
    if set_id:
        await state.update_data(current_set_id=set_id)
    await state.set_state(AddTeacherTask.waiting_question_and_image)
    await cb.message.answer("Отправьте текст задания. Можно сразу прикрепить 1 фото.")


@router.callback_query(lambda c: c.data == "tt_finish")
async def tt_finish(cb: types.CallbackQuery, state: FSMContext):
    await cb.answer()
    data = await state.get_data()
    set_id = data.get("current_set_id")
    # После завершения показываем список наборов (новая кнопка с названием уже будет в списке)
    try:
        await cb.message.edit_text("Выберите набор или создайте новый:")
        await cb.message.edit_reply_markup(reply_markup=_sets_list_kb())
    except Exception:
        await cb.message.answer("Выберите набор или создайте новый:", reply_markup=_sets_list_kb())
    await state.clear()


@router.callback_query(lambda c: c.data.startswith("tt_delete:"))
async def tt_delete_set(cb: types.CallbackQuery, state: FSMContext):
    await cb.answer()
    try:
        set_id = int(cb.data.split(":", 1)[1])
    except Exception:
        return
    ok = delete_task_set(set_id)
    msg = "✅ Набор удалён." if ok else "❌ Не удалось удалить набор."
    try:
        await cb.message.edit_text(msg)
        await cb.message.edit_reply_markup(reply_markup=_sets_list_kb())
    except Exception:
        await cb.message.answer(msg, reply_markup=_sets_list_kb())


@router.callback_query(lambda c: c.data.startswith("tt_stats:"))
async def tt_stats(cb: types.CallbackQuery):
    await cb.answer()
    try:
        set_id = int(cb.data.split(":", 1)[1])
    except Exception:
        return
    info = compute_teacher_set_results(set_id)
    title = info.get('title') or f"Набор {set_id}"
    qids = info.get('qids') or []
    results = info.get('results') or []
    lines: list[str] = []
    lines.append(f"📊 Результаты набора «{title}»")
    lines.append(f"Всего вопросов в наборе: {len(qids)}")
    lines.append("")
    if not results:
        lines.append("Пока нет ответов по этому набору.")
    else:
        lines.append("<b>Ученик — верных/всего (точность)</b>")
        for r in results:
            label = str(r.get('label') or f"ID {r.get('user_id')}")
            if len(label) > 30:
                label = label[:27] + "…"
            lines.append(f"{label} — {r['correct']}/{r['total']} ({r['pct']}%)")
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data=f"tt_set_open:{set_id}")]])
    try:
        await cb.message.edit_text("\n".join(lines), parse_mode="HTML", reply_markup=kb)
    except Exception:
        await cb.message.answer("\n".join(lines), parse_mode="HTML", reply_markup=kb)


@router.callback_query(lambda c: c.data.startswith("tt_print:"))
async def tt_print(cb: types.CallbackQuery):
    from services.pdf_export import render_questions_to_pdf
    import os, tempfile
    await cb.answer()
    try:
        set_id = int(cb.data.split(":", 1)[1])
    except Exception:
        return
    tasks = list_tasks_in_set(set_id)
    if not tasks:
        await cb.answer("Набор пуст.", show_alert=True)
        return
    # Преобразуем вопросы в формат pages для PDF
    pages: list[dict] = []
    for t in tasks:
        pages.append({
            "title": f"Задание #{t.get('id')}",
            "question": t.get("question") or "",
            # для teacher-наборов options хранит id изображения (или список id)
            "options": t.get("options") or "",
            "exam": "teacher",
            "qid": t.get("id"),
            "type": None,
        })
    tmp_dir = tempfile.mkdtemp(prefix="tt_pdf_")
    out_path = os.path.join(tmp_dir, f"teacher_set_{set_id}.pdf")
    pdf_path = render_questions_to_pdf(out_path, pages)
    try:
        from aiogram.types import FSInputFile
        await cb.message.answer_document(FSInputFile(pdf_path), caption=f"📄 Набор #{set_id}")
    except Exception:
        await cb.answer("PDF создан, но не удалось отправить", show_alert=True)
