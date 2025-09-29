from aiogram import Router, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, CallbackQuery

from bot.handlers.menu import main_kb
from bot.services.answer_db import (
    save_test_answer, save_test_progress, load_test_progress, clear_test_progress,
    get_last_results_for_questions, reset_test_results, get_user_full_name,
    log_question_started, log_question_answered,
)
from bot.services.test_sql_teacher import (
    list_test_groups, _filename_by_key, get_questions_by_filename, get_question_by_id,
    teacher_test_type, get_question_with_image
)
from bot.utils_pkg.message_manager import message_manager

router = Router()


def _grid_keyboard(user_id: int, test_type: int, q_ids: list[int]) -> InlineKeyboardMarkup:
    status = get_last_results_for_questions(user_id, test_type, q_ids)
    rows: list[list[InlineKeyboardButton]] = []
    limit = min(30, len(q_ids))
    for r in range(10):
        row: list[InlineKeyboardButton] = []
        for c in range(3):
            idx = r + 10 * c
            if idx < limit:
                st = status.get(q_ids[idx])
                mark = "✅" if st == 1 else "❌" if st == 0 else "⬜"
                row.append(InlineKeyboardButton(text=f"{idx+1}{mark}", callback_data=f"teach_jump_{test_type}_{idx+1}"))
        if row:
            rows.append(row)
    rows.append([InlineKeyboardButton(text="🔄 Начать заново", callback_data=f"teach_restart_{test_type}")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="tests_go_back")])
    rows.append([InlineKeyboardButton(text="⬅️ В главное меню", callback_data="to_main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(lambda m: (m.text or "").strip().lower() == "👨‍🏫 задания от преподавателя")
async def open_teacher_groups(m: types.Message):
    await message_manager.delete_user_messages_fast(m.bot, m.from_user.id, m.chat.id)
    groups = list_test_groups()
    if not groups:
        msg = await m.answer("Пока нет заданий от преподавателей.")
        message_manager.add_message(m.from_user.id, msg.message_id)
        return
    # Формируем 2 столбца с именами преподавателей
    kb_rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for g in groups:
        text = f"👨‍🏫 {g['teacher_name']}"
        row.append(InlineKeyboardButton(text=text, callback_data=f"teach_choose_{g['key']}"))
        if len(row) == 2:
            kb_rows.append(row)
            row = []
    if row:
        kb_rows.append(row)
    kb_rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="tests_go_back")])
    kb_rows.append([InlineKeyboardButton(text="⬅️ В главное меню", callback_data="to_main_menu")])
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    msg = await m.answer("Выбери преподавателя:", reply_markup=kb)
    message_manager.add_message(m.from_user.id, msg.message_id)


@router.callback_query(lambda c: c.data.startswith("teach_choose_"))
async def start_teacher_test(cb: CallbackQuery):
    key = int(cb.data.split("_")[-1])
    filename = _filename_by_key(key)
    if not filename:
        await cb.answer()
        return
    questions = get_questions_by_filename(filename)
    if not questions:
        await cb.message.answer("Нет вопросов от этого преподавателя.")
        await cb.answer()
        return
    test_type = teacher_test_type(filename)
    q_ids = [q["id"] for q in questions]
    clear_test_progress(cb.from_user.id, test_type)
    save_test_progress(cb.from_user.id, test_type, 0, q_ids)
    kb = _grid_keyboard(cb.from_user.id, test_type, q_ids)
    sent = await cb.message.answer("Выбери номер задания:", reply_markup=kb)
    message_manager.add_message(cb.from_user.id, sent.message_id)
    await cb.answer()


@router.callback_query(lambda c: c.data.startswith("teach_jump_"))
async def teacher_jump(cb: CallbackQuery):
    parts = cb.data.split("_")
    # teach, jump, {test_type}, {number}
    if len(parts) != 4:
        await cb.answer()
        return
    test_type = int(parts[2])
    number = max(1, int(parts[3]))
    idx, q_ids = load_test_progress(cb.from_user.id, test_type)
    if not q_ids:
        await cb.answer()
        return
    number = min(number, len(q_ids))
    save_test_progress(cb.from_user.id, test_type, number - 1, q_ids)
    await send_teacher_question(cb.from_user.id, cb.message, test_type)
    await cb.answer()


async def send_teacher_question(user_id: int, message_obj: types.Message, test_type: int):
    idx, q_ids = load_test_progress(user_id, test_type)
    if idx is None or not q_ids:
        return
    if idx >= len(q_ids):
        await message_obj.answer("Тест завершён! Возвращаюсь в меню.")
        return
    q_id = q_ids[idx]
    q = get_question_with_image(q_id)
    if not q:
        await message_obj.answer("Ошибка: вопрос не найден.")
        return
    log_question_started(user_id, test_type, q_id)
    # Формируем текст
    msg = f"Вопрос {idx+1} из {len(q_ids)}\n\n" + (q.get("question", "") or "")
    opts = q.get("options", "")
    if opts:
        msg += "\n\n" + "\n".join([f"{i+1}. {opt}" for i, opt in enumerate(opts.split("\n"))])
    msg += "\n\nВведите номер(а) ответа (например: 2 или 13):"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⏹️ Стоп", callback_data=f"teach_restart_{test_type}")]])
    # Если есть изображения — отправим фото(а); иначе обычный текст
    try:
        if q.get("image") or q.get("images"):
            from aiogram.types import BufferedInputFile, InputMediaPhoto
            if q.get("image"):
                img = q["image"]
                photo = BufferedInputFile(file=img["data"], filename=img.get("filename", "image.png"))
                sent = await message_obj.answer_photo(photo=photo, caption=msg, reply_markup=kb)
            else:
                photos = []
                for img in q.get("images", []):
                    photos.append(BufferedInputFile(file=img["data"], filename=img.get("filename", "image.png")))
                media = [InputMediaPhoto(media=photos[0], caption=msg)]
                for p in photos[1:]:
                    media.append(InputMediaPhoto(media=p))
                sent_group = await message_obj.answer_media_group(media)
                sent = sent_group[0]
                # Кнопки отдельным сообщением
                kb_msg = await message_obj.answer("Выберите действие:", reply_markup=kb)
                message_manager.add_message(user_id, kb_msg.message_id)
        else:
            sent = await message_obj.answer(msg, reply_markup=kb)
    except Exception:
        sent = await message_obj.answer(msg, reply_markup=kb)
    message_manager.add_message(user_id, sent.message_id)


@router.message(lambda m: isinstance(getattr(m, "text", None), str) and m.text.strip().isdigit())
async def teacher_answer(m: types.Message):
    # Определяем, есть ли активный teacher-тест: найдём запись прогресса с test_type>=20000
    found = None
    for tt in range(20000, 30000):
        idx, qids = load_test_progress(m.from_user.id, tt)
        if idx is not None and qids:
            found = (tt, idx, qids)
            break
    if not found:
        return
    test_type, idx, q_ids = found
    q = get_question_by_id(q_ids[idx])
    user_answer = ''.join(filter(str.isdigit, m.text))
    correct = ''.join(filter(str.isdigit, str(q.get("correct_answer", ""))))
    is_correct = (user_answer == correct)
    log_question_answered(m.from_user.id, q_ids[idx], m.text, is_correct)
    save_test_answer(
        m.from_user.id,
        getattr(m.from_user, "username", None) or m.from_user.full_name,
        test_type,
        q_ids[idx],
        q.get("question", ""),
        m.text,
        q.get("correct_answer", ""),
        is_correct,
        full_name=get_user_full_name(m.from_user.id)
    )
    # Ответ пользователю
    await m.answer("✅ Верно!" if is_correct else f"❌ Неверно. Правильный ответ: {correct}")
    # Следующий вопрос или таблица
    idx += 1
    if idx >= len(q_ids):
        clear_test_progress(m.from_user.id, test_type)
        await m.answer("Тест завершён! Возвращаюсь в меню.", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="⬅️ В меню")]], resize_keyboard=True))
        return
    save_test_progress(m.from_user.id, test_type, idx, q_ids)
    await send_teacher_question(m.from_user.id, m, test_type)


@router.callback_query(lambda c: c.data.startswith("teach_restart_"))
async def teacher_restart(cb: CallbackQuery):
    test_type = int(cb.data.split("_")[-1])
    idx, q_ids = load_test_progress(cb.from_user.id, test_type)
    if not q_ids:
        await cb.answer()
        return
    reset_test_results(cb.from_user.id, test_type)
    save_test_progress(cb.from_user.id, test_type, 0, q_ids)
    kb = _grid_keyboard(cb.from_user.id, test_type, q_ids)
    try:
        await cb.message.edit_reply_markup(reply_markup=kb)
    except Exception:
        sent = await cb.message.answer("Выбери номер задания:", reply_markup=kb)
        message_manager.add_message(cb.from_user.id, sent.message_id)
    await cb.answer()


