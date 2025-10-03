from aiogram import Router, types
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
    BufferedInputFile,
)
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
import random

from bot.utils import (
    ALL_TOPICS,  # не используется напрямую, но оставим для расширений
    clean_html,  # не используется здесь, но может пригодиться
    user_topics, # не используется здесь, но может пригодиться
    LEARNING_TOPICS,
    user_learning_state,
    TEXTBOOK_CONTENT,
    latex_to_codeblock,
    BEGIN_CHEM_TOPICS,
    ELEMENT_CHEM_TOPICS,
    get_prepared_chunks_count,
    get_prepared_lecture,
    ensure_chunk_title_column,
    get_chunk_title,
    set_chunk_title,
    get_audio_from_db,
    get_qa_questions,
    get_qa_answers,
    get_total_questions_count_for_topic,
)
from bot.handlers.menu import main_kb
from bot.services.gpt_service import answer_student_question
from bot.services.gpt_service import transcribe_audio, grade_theory_answer
from bot.services.answer_db import save_theory_task_answer, get_theory_stats, get_theory_stats_by_chunk
from bot.utils_pkg_new.logger import log_error
from bot.utils_pkg.message_manager import message_manager
import httpx
import difflib
import sqlite3
import math
import re

router = Router()

# ================== Разделы «Теории по химии» ==================

# Узкий фильтр: сообщение считается ответом на задание, только если
# у пользователя есть назначенный вопрос для текущего фрагмента
def _has_assigned_task(m: types.Message) -> bool:
    st = user_learning_state.get(m.from_user.id)
    if not st:
        return False
    assigned = st.get("assigned_tasks", {})
    key = f"{st.get('topic')}:{st.get('index')}"
    return key in assigned and not st.get("awaiting_question")

# Цветная точка прогресса рядом с названием темы
def _topic_progress_dot(user_id: int, topic: str) -> str:
    try:
        correct, _ = get_theory_stats(user_id, topic)
        # Сколько всего порций по теме
        chunks_json = TEXTBOOK_CONTENT.get(topic, [])
        total_from_json = len(chunks_json)
        total_from_db = get_prepared_chunks_count(topic)
        total = total_from_json if total_from_json > 0 else total_from_db
        if total <= 0 or correct <= 0:
            return ""  # без индикатора при отсутствии прогресса
        t_satisf = max(1, math.ceil(0.3 * total))
        t_good   = max(1, math.floor(0.5 * total) + 1)
        t_excell = max(1, math.floor(0.7 * total) + 1)
        if correct >= t_excell:
            return "🟩"   # отлично — зелёный
        if correct >= t_good:
            return "🟨"   # хорошо — жёлтый
        if correct >= t_satisf:
            return "🟥"   # удовлетворительно — красный
        return ""        # <30% — без индикатора
    except (ValueError, TypeError) as e:
        log_error(e, f"Data error in topic progress dot for user {user_id}, topic {topic}", user_id=user_id)
        return ""
    except sqlite3.OperationalError as e:
        log_error(e, f"Database error in topic progress dot for user {user_id}, topic {topic}", user_id=user_id)
        return ""
    except (AttributeError, KeyError, sqlite3.Error) as e:
        log_error(e, f"Unexpected error in topic progress dot for user {user_id}, topic {topic}", user_id=user_id)
        return "⬛"

# 1) Начала химии — список глав
@router.message(lambda m: m.text == "📖 Начала химии")
async def begin_chem(m: types.Message):
    await message_manager.delete_user_messages_fast(m.bot, m.from_user.id, m.chat.id)
    buttons = []
    for i, topic in enumerate(BEGIN_CHEM_TOPICS):
        buttons.append([InlineKeyboardButton(text=f"{topic}", callback_data=f"begin_topic_{i}")])
    # Кнопка в главное меню снизу
    buttons.append([InlineKeyboardButton(text="⬅️ В главное меню", callback_data="to_main_menu")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    sent = await m.answer("Выбери главу из раздела «Начала химии»:", reply_markup=kb)
    message_manager.add_message(m.from_user.id, sent.message_id)

# Выбор главы «Начала химии»
@router.callback_query(lambda c: c.data.startswith("begin_topic_"))
async def begin_topic_chosen(cb: types.CallbackQuery, bot):
    await cb.answer()
    await message_manager.delete_user_messages_fast(cb.message.bot, cb.from_user.id, cb.message.chat.id)
    try:
        idx = int(cb.data.split("begin_topic_")[-1])
        topic = BEGIN_CHEM_TOPICS[idx]
    except (ValueError, IndexError) as e:
        log_error(e, f"Invalid topic index in begin_topic_chosen for user {cb.from_user.id}", user_id=cb.from_user.id)
        await cb.message.answer("Не получилось определить тему. Попробуй ещё раз.", reply_markup=main_kb)
        return
    except (AttributeError, KeyError) as e:
        log_error(e, f"Unexpected error in begin_topic_chosen for user {cb.from_user.id}", user_id=cb.from_user.id)
        await cb.message.answer("Произошла ошибка. Попробуй ещё раз.", reply_markup=main_kb)
        return
    await _show_topic_parts(cb.message, cb.from_user.id, topic, section_prefix="begin", topic_index=idx)

# 2) Химия элементов — СПИСОК ГЛАВ (полноценный)
@router.message(lambda m: m.text == "⚗️ Химия элементов")
async def element_chem(m: types.Message):
    await message_manager.delete_user_messages_fast(m.bot, m.from_user.id, m.chat.id)
    from bot.services.plan import theory_allowed
    if not theory_allowed(m.from_user.id, "elements"):
        msg = await m.answer("Этот раздел доступен на тарифах ('Химия элементов', 'Самоподготовка', 'Групповые', 'Полный доступ'). Открой '💳 Тарифы и оплата'.", reply_markup=main_kb)
        message_manager.add_message(m.from_user.id, msg.message_id)
        return
    buttons = []
    for i, topic in enumerate(ELEMENT_CHEM_TOPICS):
        buttons.append([InlineKeyboardButton(text=f"{topic}", callback_data=f"element_topic_{i}")])
    # Кнопка в главное меню снизу
    buttons.append([InlineKeyboardButton(text="⬅️ В главное меню", callback_data="to_main_menu")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    msg = await m.answer("Выбери главу из раздела «Химия элементов»:", reply_markup=kb)
    message_manager.add_message(m.from_user.id, msg.message_id)

# Выбор главы «Химия элементов»
@router.callback_query(lambda c: c.data.startswith("element_topic_"))
async def element_topic_chosen(cb: types.CallbackQuery, bot):
    await cb.answer()
    await message_manager.delete_user_messages_fast(cb.message.bot, cb.from_user.id, cb.message.chat.id)
    try:
        idx = int(cb.data.split("element_topic_")[-1])
        topic = ELEMENT_CHEM_TOPICS[idx]
    except (ValueError, IndexError) as e:
        log_error(e, f"Invalid topic index in element_topic_chosen for user {cb.from_user.id}", user_id=cb.from_user.id)
        await cb.message.answer("Не получилось определить тему. Попробуй ещё раз.", reply_markup=main_kb)
        return
    except (AttributeError, KeyError) as e:
        log_error(e, f"Unexpected error in element_topic_chosen for user {cb.from_user.id}", user_id=cb.from_user.id)
        await cb.message.answer("Произошла ошибка. Попробуй ещё раз.", reply_markup=main_kb)
        return
    await _show_topic_parts(cb.message, cb.from_user.id, topic, section_prefix="element", topic_index=idx)

# 3) Органическая химия — список глав
@router.message(lambda m: m.text == "🧬 Органическая химия")
async def organic_chem(m: types.Message):
    await message_manager.delete_user_messages_fast(m.bot, m.from_user.id, m.chat.id)
    from bot.services.plan import theory_allowed
    if not theory_allowed(m.from_user.id, "organic"):
        msg = await m.answer("Этот раздел доступен на тарифах ('Органика', 'Самоподготовка', 'Групповые', 'Полный доступ'). Открой '💳 Тарифы и оплата'.", reply_markup=main_kb)
        message_manager.add_message(m.from_user.id, msg.message_id)
        return
    buttons = []
    for i, topic in enumerate(LEARNING_TOPICS):
        buttons.append([InlineKeyboardButton(text=f"{topic}", callback_data=f"learn_topic_{i}")])
    # Кнопка в главное меню снизу
    buttons.append([InlineKeyboardButton(text="⬅️ В главное меню", callback_data="to_main_menu")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    msg = await m.answer("Выбери главу из раздела «Органическая химия»:", reply_markup=kb)
    message_manager.add_message(m.from_user.id, msg.message_id)

# Выбор главы «Органическая химия»
@router.callback_query(lambda c: c.data.startswith("learn_topic_"))
async def learn_topic_chosen(cb: types.CallbackQuery, bot):
    await cb.answer()
    await message_manager.delete_user_messages_fast(cb.message.bot, cb.from_user.id, cb.message.chat.id)
    try:
        idx = int(cb.data.split("learn_topic_")[-1])
        topic = LEARNING_TOPICS[idx]
    except (ValueError, IndexError) as e:
        log_error(e, f"Invalid topic index in learn_topic_chosen for user {cb.from_user.id}", user_id=cb.from_user.id)
        await cb.message.answer("Не получилось определить тему. Попробуй ещё раз.", reply_markup=main_kb)
        return
    except (AttributeError, KeyError) as e:
        log_error(e, f"Unexpected error in learn_topic_chosen for user {cb.from_user.id}", user_id=cb.from_user.id)
        await cb.message.answer("Произошла ошибка. Попробуй ещё раз.", reply_markup=main_kb)
        return
    await _show_topic_parts(cb.message, cb.from_user.id, topic, section_prefix="learn", topic_index=idx)

# ================== Список частей выбранной главы ==================
async def _show_topic_parts(msg: types.Message, user_id: int, topic: str, *, section_prefix: str, topic_index: int) -> None:
    """Показывает кнопки частей главы с прогрессом по вопросам: correct/total."""
    # Чистим прошлые одноразовые сообщения перед показом списка частей
    try:
        await message_manager.delete_user_messages_fast(msg.bot, user_id, msg.chat.id)
    except Exception:
        pass
    # Фолбэк: снесём несколько последних сообщений в чате (если менеджер чего‑то не знал)
    try:
        base = msg.message_id
        for delta in range(0, 2):
            try:
                await msg.bot.delete_message(chat_id=msg.chat.id, message_id=base - delta)
            except Exception:
                pass
    except Exception:
        pass
    # Сколько частей всего по этой главе
    total_chunks = get_prepared_chunks_count(topic)
    if total_chunks <= 0:
        await msg.answer(f"По теме «{topic}» пока нет подготовленных частей.", reply_markup=main_kb)
        return

    # Статистика по каждой части: chunk_idx -> (correct, total)
    stats = get_theory_stats_by_chunk(user_id, topic)
    # Убедимся, что столбец для заголовков есть
    ensure_chunk_title_column()

    # Генерацию заголовков на лету убрали ради скорости

    # Собираем клавиатуру: по 1 кнопке в строке (чтобы было видно длинные заголовки)
    rows: list[list[InlineKeyboardButton]] = []
    for i in range(total_chunks):
        correct, total = stats.get(i, (0, 0))
        if total == 0:
            # если в таблице ещё нет total — посчитаем напрямую
            try:
                from bot.utils import get_qa_questions as _qq
                total = len(_qq(topic, i))
            except (ValueError, TypeError) as e:
                log_error(e, f"Data error getting QA questions for topic {topic}, chunk {i}, user {user_id}", user_id=user_id)
                total = 0
            except (AttributeError, KeyError, sqlite3.Error) as e:
                log_error(e, f"Unexpected error getting QA questions for topic {topic}, chunk {i}, user {user_id}", user_id=user_id)
                total = 0
        # Заголовок части (если есть), иначе номер
        title = get_chunk_title(topic, i) or f"Часть {i+1}"
        # Переносим прогресс на вторую строку, чтобы название было видно целиком
        # Эмодзи статуса по проценту выполнения: 0 — нет, >0 — 🟨, ≥70% — 🟩
        if total and correct:
            ratio = (correct / max(1, total))
            emoji = "🟩" if ratio >= 0.7 else "🟨"
        else:
            emoji = ""
        prefix = (emoji + " ") if emoji else ""
        text = f"{i+1}. {title}\n{prefix}{correct} / {total}"
        cb_data = f"{section_prefix}_part_{topic_index}_{i}"
        rows.append([InlineKeyboardButton(text=text, callback_data=cb_data)])

    # Кнопка «К главам» и «В главное меню»
    rows.append([InlineKeyboardButton(text="📚 К главам", callback_data=f"parts_to_chapters_{section_prefix}")])
    rows.append([InlineKeyboardButton(text="⬅️ В главное меню", callback_data="to_main_menu_from_parts")])
    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    sent = await msg.answer(f"Глава: «{topic}»\nВыбери часть:", reply_markup=kb)
    try:
        message_manager.add_message(user_id, sent.message_id)
    except Exception:
        pass

# Переход к нужной части — Начала химии
@router.callback_query(lambda c: c.data.startswith("begin_part_"))
async def begin_part_start(cb: types.CallbackQuery, bot):
    try:
        _prefix, _p, t_idx, ch_idx = cb.data.split("_")
        topic = BEGIN_CHEM_TOPICS[int(t_idx)]
        part = int(ch_idx)
    except (ValueError, IndexError) as e:
        log_error(e, f"Invalid part data in begin_part_start for user {cb.from_user.id}", user_id=cb.from_user.id)
        await cb.answer("Ошибка данных. Попробуй ещё раз.")
        return
    except (AttributeError, KeyError) as e:
        log_error(e, f"Unexpected error in begin_part_start for user {cb.from_user.id}", user_id=cb.from_user.id)
        await cb.answer("Произошла ошибка. Попробуй ещё раз.")
        return
    user_learning_state[cb.from_user.id] = {"topic": topic, "index": part, "awaiting_question": False}
    await send_next_chunk(cb.from_user.id, bot)

# Переход к нужной части — Химия элементов
@router.callback_query(lambda c: c.data.startswith("element_part_"))
async def element_part_start(cb: types.CallbackQuery, bot):
    try:
        _prefix, _p, t_idx, ch_idx = cb.data.split("_")
        topic = ELEMENT_CHEM_TOPICS[int(t_idx)]
        part = int(ch_idx)
    except (ValueError, IndexError) as e:
        log_error(e, f"Invalid part data in element_part_start for user {cb.from_user.id}", user_id=cb.from_user.id)
        await cb.answer("Ошибка данных. Попробуй ещё раз.")
        return
    except (AttributeError, KeyError) as e:
        log_error(e, f"Unexpected error in element_part_start for user {cb.from_user.id}", user_id=cb.from_user.id)
        await cb.answer("Произошла ошибка. Попробуй ещё раз.")
        return
    user_learning_state[cb.from_user.id] = {"topic": topic, "index": part, "awaiting_question": False}
    await send_next_chunk(cb.from_user.id, bot)

# Переход к нужной части — Органическая химия
@router.callback_query(lambda c: c.data.startswith("learn_part_"))
async def learn_part_start(cb: types.CallbackQuery, bot):
    try:
        _prefix, _p, t_idx, ch_idx = cb.data.split("_")
        topic = LEARNING_TOPICS[int(t_idx)]
        part = int(ch_idx)
    except (ValueError, IndexError) as e:
        log_error(e, f"Invalid part data in learn_part_start for user {cb.from_user.id}", user_id=cb.from_user.id)
        await cb.answer("Ошибка данных. Попробуй ещё раз.")
        return
    except (AttributeError, KeyError) as e:
        log_error(e, f"Unexpected error in learn_part_start for user {cb.from_user.id}", user_id=cb.from_user.id)
        await cb.answer("Произошла ошибка. Попробуй ещё раз.")
        return
    user_learning_state[cb.from_user.id] = {"topic": topic, "index": part, "awaiting_question": False}
    await send_next_chunk(cb.from_user.id, bot)

# ================== Универсальный показ следующего chunk ==================
async def send_next_chunk(user_id: int, bot):
    st = user_learning_state.get(user_id)
    if not st:
        return
    # Чистим прошлые одноразовые сообщения перед новой лекцией
    try:
        from bot.utils_pkg.message_manager import message_manager as _mm
        # Попробуем удалить в приват чате user_id (в теории сообщения лекций идут в ЛС)
        await _mm.delete_user_messages(bot, user_id, user_id)
    except Exception:
        pass

    topic = st["topic"]
    idx = st["index"]

    # Определяем список глав для корректной нумерации
    if topic in LEARNING_TOPICS:
        chapter_list = LEARNING_TOPICS
    elif topic in BEGIN_CHEM_TOPICS:
        chapter_list = BEGIN_CHEM_TOPICS
    elif topic in ELEMENT_CHEM_TOPICS:
        chapter_list = ELEMENT_CHEM_TOPICS
    else:
        chapter_list = [topic]

    chap_num = chapter_list.index(topic) + 1 if topic in chapter_list else 1
    chap_total = len(chapter_list)

    # Доступные порции теории: JSON и/или БД
    chunks_json = TEXTBOOK_CONTENT.get(topic, [])
    total_from_json = len(chunks_json)
    total_from_db = get_prepared_chunks_count(topic)
    total = total_from_json if total_from_json > 0 else total_from_db

    if total == 0:
        await bot.send_message(
            user_id,
            f"По теме «{topic}» пока нет подготовленной лекции.",
            reply_markup=main_kb,
        )
        user_learning_state.pop(user_id, None)
        return

    if idx >= total:
        await bot.send_message(
            user_id,
            f"Глава «{topic}» пройдена! 🎉",
            reply_markup=main_kb,
        )
        user_learning_state.pop(user_id, None)
        return

    # Берём лекцию из БД (приоритет) или из JSON
    raw = get_prepared_lecture(topic, idx)
    if not raw and total_from_json:
        raw = chunks_json[idx] if idx < len(chunks_json) else None

    if not raw:
        await bot.send_message(
            user_id,
            "Лекция пока не подготовлена. Сообщи администратору.",
            reply_markup=main_kb,
        )
        return

    header = f"Глава {chap_num}/{chap_total}, порция {idx+1}/{total}\n\n"
    formatted = latex_to_codeblock(raw)

    # Проверяем длину текста (Telegram лимит ~4096 символов)
    full_text = header + formatted
    if len(full_text) > 4000:
        # Если текст слишком длинный, обрезаем его
        formatted = formatted[:4000 - len(header) - 50] + "\n\n... (текст обрезан из-за ограничений Telegram)"
        full_text = header + formatted

    # Проверяем наличие аудио для этого фрагмента
    audio_data = get_audio_from_db(topic, idx)
    has_audio = audio_data is not None
    # Запомним в состоянии, чтобы уметь корректно редактировать клавиатуру позже
    st["has_audio"] = has_audio

    # Создаем клавиатуру с кнопкой аудио если есть аудио
    keyboard_buttons = [
        [
            InlineKeyboardButton(text="◀️ Назад", callback_data="learn_back"),
            InlineKeyboardButton(text="Далее", callback_data="learn_ok"),
        ],
        [InlineKeyboardButton(text="📝 Задание", callback_data="learn_task")],
        [
            InlineKeyboardButton(text="❓ Спросить ИИ", callback_data="learn_ask"),
            InlineKeyboardButton(text="↩️ К частям", callback_data="learn_to_parts"),
            InlineKeyboardButton(text="🏠 К главам", callback_data="learn_to_chapters"),
        ],
    ]
    
    # Добавляем кнопку аудио если есть аудио
    if has_audio:
        keyboard_buttons.insert(2, [
            InlineKeyboardButton(text="🔊 Слушать аудио", callback_data="learn_audio")
        ])

    kb = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

    # Пытаемся отправить с Markdown, если не получается - отправляем без него
    try:
        sent_msg = await bot.send_message(
            user_id,
            header + formatted,
            reply_markup=kb,
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as e:
        # Если Markdown не работает, отправляем как обычный текст
        log_error(e, f"Markdown parsing failed for user {user_id}, falling back to plain text", user_id=user_id)
        try:
            # Убираем все Markdown-разметку и отправляем как обычный текст
            plain_text = re.sub(r'```[\s\S]*?```', '', header + formatted)  # Убираем code blocks
            plain_text = re.sub(r'\*([^*]+)\*', r'\1', plain_text)  # Убираем *жирный*
            plain_text = re.sub(r'_([^_]+)_', r'\1', plain_text)    # Убираем _курсив_
            plain_text = re.sub(r'`([^`]+)`', r'\1', plain_text)    # Убираем `код`
            
            sent_msg = await bot.send_message(
                user_id,
                plain_text,
                reply_markup=kb,
                parse_mode=None,  # Без Markdown
            )
        except Exception as fallback_error:
            # Если и это не работает, отправляем только заголовок
            log_error(fallback_error, f"Both Markdown and plain text failed for user {user_id}", user_id=user_id)
            sent_msg = await bot.send_message(
                user_id,
                f"Ошибка отображения текста лекции. Обратитесь к администратору.\n\n{header}",
                reply_markup=kb,
                parse_mode=None,
            )
    try:
        st["last_lecture_msg_id"] = sent_msg.message_id
    except (ValueError, TypeError) as e:
        log_error(e, f"Data error setting last_lecture_msg_id for user {user_id}", user_id=user_id)
    except (AttributeError, KeyError) as e:
        log_error(e, f"Unexpected error setting last_lecture_msg_id for user {user_id}", user_id=user_id)
    try:
        from bot.utils_pkg.message_manager import message_manager as _mm
        _mm.add_message(user_id, sent_msg.message_id)
    except Exception:
        pass

# ================== Навигация ==================
@router.callback_query(lambda c: c.data == "learn_ok")
async def learn_ok(cb: types.CallbackQuery, bot):
    st = user_learning_state.get(cb.from_user.id)
    if st:
        st["index"] += 1
    await send_next_chunk(cb.from_user.id, bot)

@router.callback_query(lambda c: c.data == "learn_back")
async def learn_back(cb: types.CallbackQuery, bot):
    st = user_learning_state.get(cb.from_user.id)
    if st and st["index"] > 0:
        st["index"] -= 1
    await send_next_chunk(cb.from_user.id, bot)

@router.callback_query(lambda c: c.data == "learn_stop")
async def learn_stop(cb: types.CallbackQuery):
    user_learning_state.pop(cb.from_user.id, None)
    # Убираем старые инлайн-кнопки у сообщения с теорией,
    # чтобы после «Стоп» нельзя было нажать «К главам» без проверок
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except (ValueError, TypeError) as e:
        log_error(e, f"Data error editing reply markup in learn_stop for user {cb.from_user.id}", user_id=cb.from_user.id)
    except (AttributeError, KeyError) as e:
        log_error(e, f"Unexpected error editing reply markup in learn_stop for user {cb.from_user.id}", user_id=cb.from_user.id)
    await cb.message.answer("Обучение остановлено.", reply_markup=main_kb)

@router.callback_query(lambda c: c.data == "learn_audio")
async def learn_audio(cb: types.CallbackQuery, bot):
    """Обработчик кнопки аудио - отправляет аудиофайл пользователю"""
    st = user_learning_state.get(cb.from_user.id)
    if not st:
        await cb.answer("Ошибка: состояние обучения не найдено")
        return
    
    topic = st["topic"]
    idx = st["index"]
    
    # Получаем аудио из базы данных
    audio_data = get_audio_from_db(topic, idx)
    if not audio_data:
        await cb.answer("Аудио для этого фрагмента не найдено")
        return
    
    audio_blob, audio_format, duration_ms = audio_data
    
    try:
        # Отправляем аудио как голосовое сообщение
        sent_voice = await bot.send_voice(
            chat_id=cb.from_user.id,
            voice=BufferedInputFile(
                audio_blob, 
                filename=f"{topic}_chunk_{idx}.{audio_format}"
            ),
            caption=f"🔊 Аудио к фрагменту «{topic}» (часть {idx+1})"
        )
        await cb.answer("Аудио отправлено!")
        try:
            message_manager.add_message(cb.from_user.id, sent_voice.message_id)
        except Exception:
            pass
        
    except (ValueError, TypeError) as e:
        log_error(e, f"Data error sending audio for user {cb.from_user.id}", user_id=cb.from_user.id)
        await cb.answer("Ошибка данных при отправке аудио")
    except (AttributeError, KeyError, httpx.RequestError) as e:
        log_error(e, f"Unexpected error sending audio for user {cb.from_user.id}", user_id=cb.from_user.id)
        await cb.answer(f"Ошибка отправки аудио: {str(e)}")

@router.callback_query(lambda c: c.data == "learn_to_parts")
async def learn_to_parts(cb: types.CallbackQuery, bot):
    """Закрывает текущую главу и показывает список частей выбранной темы."""
    try:
        await message_manager.delete_user_messages_fast(cb.message.bot, cb.from_user.id, cb.message.chat.id)
    except Exception:
        pass
    st = user_learning_state.get(cb.from_user.id)
    if not st:
        await cb.answer("Нет активной главы")
        return
    topic = st.get("topic")
    # Удалим сообщения главы/заданий/результата, если есть
    try:
        msg_id = st.get("last_lecture_msg_id")
        if msg_id:
            await cb.message.bot.delete_message(chat_id=cb.message.chat.id, message_id=msg_id)
    except TelegramBadRequest as e:
        log_error(e, f"BadRequest deleting lecture message for user {cb.from_user.id}", user_id=cb.from_user.id)
    except (ValueError, TypeError) as e:
        log_error(e, f"Data error deleting lecture message for user {cb.from_user.id}", user_id=cb.from_user.id)
    except (AttributeError, KeyError) as e:
        log_error(e, f"Unexpected error deleting lecture message for user {cb.from_user.id}", user_id=cb.from_user.id)
    try:
        msg_id = st.get("last_task_msg_id")
        if msg_id:
            await cb.message.bot.delete_message(chat_id=cb.message.chat.id, message_id=msg_id)
            st.pop("last_task_msg_id", None)
    except TelegramBadRequest as e:
        log_error(e, f"BadRequest deleting task message for user {cb.from_user.id}", user_id=cb.from_user.id)
    except (ValueError, TypeError) as e:
        log_error(e, f"Data error deleting task message for user {cb.from_user.id}", user_id=cb.from_user.id)
    except (AttributeError, KeyError) as e:
        log_error(e, f"Unexpected error deleting task message for user {cb.from_user.id}", user_id=cb.from_user.id)
    try:
        msg_id = st.get("last_result_msg_id")
        if msg_id:
            await cb.message.bot.delete_message(chat_id=cb.message.chat.id, message_id=msg_id)
            st.pop("last_result_msg_id", None)
    except TelegramBadRequest as e:
        log_error(e, f"BadRequest deleting result message for user {cb.from_user.id}", user_id=cb.from_user.id)
    except (ValueError, TypeError) as e:
        log_error(e, f"Data error deleting result message for user {cb.from_user.id}", user_id=cb.from_user.id)
    except (AttributeError, KeyError) as e:
        log_error(e, f"Unexpected error deleting result message for user {cb.from_user.id}", user_id=cb.from_user.id)
    # Чистим состояние после удаления
    user_learning_state.pop(cb.from_user.id, None)
    # Определяем секцию и индекс темы
    if topic in BEGIN_CHEM_TOPICS:
        prefix = "begin"
        t_idx = BEGIN_CHEM_TOPICS.index(topic)
    elif topic in ELEMENT_CHEM_TOPICS:
        prefix = "element"
        t_idx = ELEMENT_CHEM_TOPICS.index(topic)
    else:
        prefix = "learn"
        t_idx = LEARNING_TOPICS.index(topic) if topic in LEARNING_TOPICS else 0

    await _show_topic_parts(cb.message, cb.from_user.id, topic, section_prefix=prefix, topic_index=t_idx)
    await cb.answer()


@router.callback_query(lambda c: c.data.startswith("parts_to_chapters_"))
async def parts_to_chapters(cb: types.CallbackQuery):
    """Из списка частей перейти назад к списку глав соответствующего раздела."""
    try:
        _, section_prefix = cb.data.split("parts_to_chapters_")
    except (ValueError, IndexError) as e:
        log_error(e, f"Invalid callback data in parts_to_chapters for user {cb.from_user.id}", user_id=cb.from_user.id)
        await cb.answer("Ошибка данных. Попробуй ещё раз.")
        return
    except (AttributeError, KeyError) as e:
        log_error(e, f"Unexpected error in parts_to_chapters for user {cb.from_user.id}", user_id=cb.from_user.id)
        await cb.answer("Произошла ошибка. Попробуй ещё раз.")
        return

    # Удалим сообщение со списком частей
    try:
        await cb.message.delete()
    except TelegramBadRequest:
        # Сообщение уже удалено — это нормальная ситуация, тихо игнорируем
        pass
    except (ValueError, TypeError) as e:
        log_error(e, f"Data error deleting message in parts_to_chapters for user {cb.from_user.id}", user_id=cb.from_user.id)
    except (AttributeError, KeyError) as e:
        log_error(e, f"Unexpected error deleting message in parts_to_chapters for user {cb.from_user.id}", user_id=cb.from_user.id)

    if section_prefix == "begin":
        buttons = [[InlineKeyboardButton(text=f"{t}", callback_data=f"begin_topic_{i}")]
                   for i, t in enumerate(BEGIN_CHEM_TOPICS)]
        # Добавляем кнопку "В главное меню" в отдельной строке
        buttons.append([InlineKeyboardButton(text="⬅️ В главное меню", callback_data="to_main_menu")])
        await cb.message.answer("Выбери главу из раздела «Начала химии»:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    elif section_prefix == "element":
        from bot.services.plan import theory_allowed
        if not theory_allowed(cb.from_user.id, "elements"):
            await cb.message.answer("Этот раздел доступен на тарифах ('Химия элементов', 'Самоподготовка', 'Групповые', 'Полный доступ'). Открой '💳 Тарифы и оплата'.", reply_markup=main_kb)
            await cb.answer()
            return
        buttons = [[InlineKeyboardButton(text=f"{t}", callback_data=f"element_topic_{i}")]
                   for i, t in enumerate(ELEMENT_CHEM_TOPICS)]
        # Добавляем кнопку "В главное меню" в отдельной строке
        buttons.append([InlineKeyboardButton(text="⬅️ В главное меню", callback_data="to_main_menu")])
        await cb.message.answer("Выбери главу из раздела «Химия элементов»:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    else:
        from bot.services.plan import theory_allowed
        if not theory_allowed(cb.from_user.id, "organic"):
            await cb.message.answer("Этот раздел доступен на тарифах ('Органика', 'Самоподготовка', 'Групповые', 'Полный доступ'). Открой '💳 Тарифы и оплата'.", reply_markup=main_kb)
            await cb.answer()
            return
        buttons = [[InlineKeyboardButton(text=f"{t}", callback_data=f"learn_topic_{i}")]
                   for i, t in enumerate(LEARNING_TOPICS)]
        # Добавляем кнопку "В главное меню" в отдельной строке
        buttons.append([InlineKeyboardButton(text="⬅️ В главное меню", callback_data="to_main_menu")])
        await cb.message.answer("Выбери главу из раздела «Органическая химия»:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

    await cb.answer()


@router.callback_query(lambda c: c.data == "to_main_menu_from_parts")
async def to_main_menu_from_parts(cb: types.CallbackQuery):
    """Удаляет сообщение со списком частей и открывает главное меню (Reply)."""
    # Удаляем все одноразовые сообщения в чате пользователя
    try:
        await message_manager.delete_user_messages_fast(cb.message.bot, cb.from_user.id, cb.message.chat.id)
    except Exception:
        pass
    try:
        await cb.message.delete()
    except TelegramBadRequest:
        # Сообщение уже удалено — это нормальная ситуация, тихо игнорируем
        pass
    except (ValueError, TypeError) as e:
        log_error(e, f"Data error deleting message in to_main_menu_from_parts for user {cb.from_user.id}", user_id=cb.from_user.id)
    except (AttributeError, KeyError) as e:
        log_error(e, f"Unexpected error deleting message in to_main_menu_from_parts for user {cb.from_user.id}", user_id=cb.from_user.id)
    from bot.handlers.menu import main_kb
    sent = await cb.message.answer("Главное меню:", reply_markup=main_kb)
    try:
        message_manager.add_message(cb.from_user.id, sent.message_id)
    except Exception:
        pass
    await cb.answer()

@router.callback_query(lambda c: c.data == "learn_task")
async def learn_task(cb: types.CallbackQuery):
    """Отправляет вопросы из prepared_lectures.qa_questions по текущему фрагменту."""
    st = user_learning_state.get(cb.from_user.id)
    if not st:
        await cb.answer("Нет активной главы")
        return

    topic = st["topic"]
    idx = st["index"]
    questions = get_qa_questions(topic, idx)
    if not questions:
        await cb.message.answer("Пока нет задания для этого фрагмента.")
        await cb.answer()
        return

    # Инициализируем структуры для отслеживания прогресса
    assigned = st.setdefault("assigned_tasks", {})  # key: "topic:idx" -> q_index
    wrong_questions = st.setdefault("wrong_questions", {})  # key: "topic:idx" -> set of wrong question indices
    all_answered = st.setdefault("all_answered", {})  # key: "topic:idx" -> bool
    answered_questions = st.setdefault("answered_questions", {})  # key: "topic:idx" -> set of answered question indices
    
    key = f"{topic}:{idx}"
    
    # Проверяем, все ли вопросы уже отвечены
    if all_answered.get(key, False):
        # Если все отвечены, показываем только ошибочные
        wrong_set = wrong_questions.get(key, set())
        if not wrong_set:
            await cb.message.answer("🎉 Отлично! Все вопросы решены правильно! Переходи к следующей части.")
            await cb.answer()
            return
        
        # Выбираем следующий ошибочный вопрос
        if key not in assigned:
            q_index = min(wrong_set)  # Начинаем с первого ошибочного
        else:
            current_idx = assigned[key]
            # Находим следующий ошибочный вопрос после текущего
            next_wrong = None
            for wrong_idx in sorted(wrong_set):
                if wrong_idx > current_idx:
                    next_wrong = wrong_idx
                    break
            if next_wrong is None:
                # Если не нашли следующий, берём первый ошибочный
                next_wrong = min(wrong_set)
            q_index = next_wrong
        
        assigned[key] = q_index
        question_text = questions[q_index]
        total_in_chunk = len(questions)
        text = (
            "🔄 Работа над ошибками\n"
            f"«{topic}», часть {idx+1}\n\n"
            f"Вопрос №{q_index+1}/{total_in_chunk}: {question_text}\n\n"
            f"Этот вопрос был решён неправильно. Попробуй ещё раз!"
        )
    else:
        # Обычный режим: показываем только неотвеченные вопросы
        answered_set = answered_questions.get(key, set())
        all_questions = set(range(len(questions)))
        unanswered_questions = all_questions - answered_set
        
        if not unanswered_questions:
            # Все вопросы отвечены, переходим к режиму работы над ошибками
            all_answered[key] = True
            wrong_set = wrong_questions.get(key, set())
            if wrong_set:
                q_index = min(wrong_set)  # Переходим к первому ошибочному
                text = (
                    "🔄 Все вопросы пройдены! Теперь работаем над ошибками.\n"
                    f"«{topic}», часть {idx+1}\n\n"
                    f"Вопрос №{q_index+1}/{len(questions)}: {questions[q_index]}\n\n"
                    f"Этот вопрос был решён неправильно. Попробуй ещё раз!"
                )
            else:
                await cb.message.answer("🎉 Отлично! Все вопросы решены правильно! Переходи к следующей части.")
                await cb.answer()
                return
        else:
            # Выбираем следующий неотвеченный вопрос
            if key not in assigned:
                q_index = min(unanswered_questions)  # Начинаем с первого неотвеченного
            else:
                current_idx = assigned[key]
                # Находим следующий неотвеченный вопрос после текущего
                next_unanswered = None
                for unanswered_idx in sorted(unanswered_questions):
                    if unanswered_idx > current_idx:
                        next_unanswered = unanswered_idx
                        break
                if next_unanswered is None:
                    # Если не нашли следующий, берём первый неотвеченный
                    next_unanswered = min(unanswered_questions)
                q_index = next_unanswered
            
            question_text = questions[q_index]
            total_in_chunk = len(questions)
            total_in_topic = get_total_questions_count_for_topic(topic)
            text = (
                "📝 Задание по теме\n"
                f"«{topic}», часть {idx+1} (в этом куске: {total_in_chunk}, всего по теме: {total_in_topic})\n\n"
                f"Вопрос №{q_index+1}/{total_in_chunk}: {question_text}\n\nНапиши ответ текстом или отправь голосовое."
            )
        
        assigned[key] = q_index


    # Удалим предыдущий текст задания, если он был
    try:
        prev_id = st.get("last_task_msg_id")
        if prev_id:
            await cb.message.bot.delete_message(chat_id=cb.message.chat.id, message_id=prev_id)
    except TelegramBadRequest as e:
        log_error(e, f"BadRequest deleting previous task message for user {cb.from_user.id}", user_id=cb.from_user.id)
    except (ValueError, TypeError) as e:
        log_error(e, f"Data error deleting previous task message for user {cb.from_user.id}", user_id=cb.from_user.id)
    except (AttributeError, KeyError) as e:
        log_error(e, f"Unexpected error deleting previous task message for user {cb.from_user.id}", user_id=cb.from_user.id)
    # Удалим карточку результата, если она была
    try:
        res_id = st.get("last_result_msg_id")
        if res_id:
            await cb.message.bot.delete_message(chat_id=cb.message.chat.id, message_id=res_id)
            st.pop("last_result_msg_id", None)
    except TelegramBadRequest as e:
        log_error(e, f"BadRequest deleting result message for user {cb.from_user.id}", user_id=cb.from_user.id)
    except (ValueError, TypeError) as e:
        log_error(e, f"Data error deleting result message for user {cb.from_user.id}", user_id=cb.from_user.id)
    except (AttributeError, KeyError) as e:
        log_error(e, f"Unexpected error deleting result message for user {cb.from_user.id}", user_id=cb.from_user.id)
    sent = await cb.message.answer(text)
    st["last_task_msg_id"] = sent.message_id
    try:
        message_manager.add_message(cb.from_user.id, sent.message_id)
    except Exception:
        pass
    # После показа задания скрываем кнопку «Спросить ИИ» до следующего вопроса
    try:
        st = user_learning_state.get(cb.from_user.id) or {}
        has_audio = bool(st.get("has_audio"))
        keyboard_buttons = [
            [
                InlineKeyboardButton(text="◀️ Назад", callback_data="learn_back"),
                InlineKeyboardButton(text="Далее", callback_data="learn_ok"),
            ],
            [InlineKeyboardButton(text="📝 Задание", callback_data="learn_task")],
        ]
        if has_audio:
            keyboard_buttons.append([InlineKeyboardButton(text="🔊 Слушать аудио", callback_data="learn_audio")])
        keyboard_buttons.append([
            InlineKeyboardButton(text="↩️ К частям", callback_data="learn_to_parts"),
            InlineKeyboardButton(text="🏠 К главам", callback_data="learn_to_chapters"),
        ])
        await cb.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard_buttons))
    except (ValueError, TypeError) as e:
        log_error(e, f"Data error editing reply markup in learn_task for user {cb.from_user.id}", user_id=cb.from_user.id)
    except (AttributeError, KeyError) as e:
        log_error(e, f"Unexpected error editing reply markup in learn_task for user {cb.from_user.id}", user_id=cb.from_user.id)
    await cb.answer()

@router.callback_query(lambda c: c.data == "learn_task_next")
async def learn_task_next(cb: types.CallbackQuery):
    """Выдаёт следующий вопрос по порядку или следующий ошибочный."""
    st = user_learning_state.get(cb.from_user.id)
    if not st:
        await cb.answer("Нет активной главы")
        return
    
    topic = st["topic"]
    idx = st["index"]
    questions = get_qa_questions(topic, idx)
    if len(questions) < 2:
        await cb.answer("Другого вопроса нет")
        return
    
    assigned = st.setdefault("assigned_tasks", {})
    wrong_questions = st.setdefault("wrong_questions", {})
    all_answered = st.setdefault("all_answered", {})
    answered_questions = st.setdefault("answered_questions", {})
    
    key = f"{topic}:{idx}"
    
    if all_answered.get(key, False):
        # Режим работы над ошибками
        wrong_set = wrong_questions.get(key, set())
        if not wrong_set:
            await cb.message.answer("🎉 Все ошибки исправлены! Переходи к следующей части.")
            await cb.answer()
            return
        
        current_idx = assigned.get(key, 0)
        # Находим следующий ошибочный вопрос
        next_wrong = None
        for wrong_idx in sorted(wrong_set):
            if wrong_idx > current_idx:
                next_wrong = wrong_idx
                break
        if next_wrong is None:
            next_wrong = min(wrong_set)  # Циклически к первому
        
        assigned[key] = next_wrong
        question_text = questions[next_wrong]
        text = (
            "🔄 Работа над ошибками\n"
            f"«{topic}», часть {idx+1}\n\n"
            f"Вопрос №{next_wrong+1}/{len(questions)}: {question_text}\n\n"
            f"Этот вопрос был решён неправильно. Попробуй ещё раз!"
        )
    else:
        # Обычный режим: показываем только неотвеченные вопросы
        answered_set = answered_questions.get(key, set())
        all_questions = set(range(len(questions)))
        unanswered_questions = all_questions - answered_set
        
        if not unanswered_questions:
            # Все вопросы отвечены, переходим к режиму работы над ошибками
            all_answered[key] = True
            wrong_set = wrong_questions.get(key, set())
            if wrong_set:
                new_idx = min(wrong_set)  # Переходим к первому ошибочному
                text = (
                    "🔄 Все вопросы пройдены! Теперь работаем над ошибками.\n"
                    f"«{topic}», часть {idx+1}\n\n"
                    f"Вопрос №{new_idx+1}/{len(questions)}: {questions[new_idx]}\n\n"
                    f"Этот вопрос был решён неправильно. Попробуй ещё раз!"
                )
            else:
                await cb.message.answer("🎉 Отлично! Все вопросы решены правильно! Переходи к следующей части.")
                await cb.answer()
                return
        else:
            # Выбираем следующий неотвеченный вопрос
            current_idx = assigned.get(key, 0)
            next_unanswered = None
            for unanswered_idx in sorted(unanswered_questions):
                if unanswered_idx > current_idx:
                    next_unanswered = unanswered_idx
                    break
            if next_unanswered is None:
                next_unanswered = min(unanswered_questions)  # Циклически к первому неотвеченному
            
            new_idx = next_unanswered
            question_text = questions[new_idx]
            text = (
                "📝 Задание по теме\n"
                f"«{topic}», часть {idx+1}\n\n"
                f"Вопрос №{new_idx+1}/{len(questions)}: {question_text}\n\nНапиши ответ сообщением."
            )
        
        assigned[key] = new_idx
    # Удалим предыдущий текст задания, если он был
    try:
        prev_id = st.get("last_task_msg_id")
        if prev_id:
            await cb.message.bot.delete_message(chat_id=cb.message.chat.id, message_id=prev_id)
    except (ValueError, TypeError) as e:
        log_error(e, f"Data error deleting previous task message in learn_task_next for user {cb.from_user.id}", user_id=cb.from_user.id)
    except (AttributeError, KeyError) as e:
        log_error(e, f"Unexpected error deleting previous task message in learn_task_next for user {cb.from_user.id}", user_id=cb.from_user.id)
    # Удалим карточку результата, если она была
    try:
        res_id = st.get("last_result_msg_id")
        if res_id:
            await cb.message.bot.delete_message(chat_id=cb.message.chat.id, message_id=res_id)
            st.pop("last_result_msg_id", None)
    except (ValueError, TypeError) as e:
        log_error(e, f"Data error deleting result message in learn_task_next for user {cb.from_user.id}", user_id=cb.from_user.id)
    except (AttributeError, KeyError) as e:
        log_error(e, f"Unexpected error deleting result message in learn_task_next for user {cb.from_user.id}", user_id=cb.from_user.id)
    sent = await cb.message.answer(text)
    st["last_task_msg_id"] = sent.message_id
    try:
        message_manager.add_message(cb.from_user.id, sent.message_id)
    except Exception:
        pass
    await cb.answer("Готово")

# ====== Приём текста/голоса как ответа на задание ======
@router.message(lambda m: _has_assigned_task(m))
async def catch_task_answer(m: types.Message):
    st = user_learning_state.get(m.from_user.id)
    if not st:
        return
    # проверяем: есть ли назначенный вопрос для текущего фрагмента
    topic = st.get("topic")
    idx = st.get("index")
    assigned = st.get("assigned_tasks", {})
    key = f"{topic}:{idx}"
    if key not in assigned:
        return  # пользователь не запрашивал вопрос

    q_index = assigned[key]
    questions = get_qa_questions(topic, idx)
    if not questions or q_index >= len(questions):
        return
    question_text = questions[q_index]

    # Определяем тип ответа и извлекаем текст
    answer_text = None
    answer_type = None
    voice_file_id = None

    if m.text is not None and m.text.strip():
        answer_type = "text"
        answer_text = m.text.strip()
    elif getattr(m, "voice", None):
        from bot.services.plan import get_user_plan_code, limits_for, consume_daily
        plan = get_user_plan_code(m.from_user.id)
        limit = limits_for(plan)["theory_voice_per_day"]
        ok, _left = consume_daily(m.from_user.id, "theory_voice", limit)
        if not ok:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💳 Тарифы и оплата", callback_data="to_tariffs")]
            ])
            await m.answer("Лимит голосовых ответов на сегодня исчерпан. Оформи подписку для безлимита.", reply_markup=kb)
            return
        answer_type = "voice"
        voice_file_id = m.voice.file_id
        try:
            # Скачиваем файл и транскрибируем
            file = await m.bot.get_file(m.voice.file_id)
            file_path = file.file_path
            # Telegram URL для скачивания
            url = f"https://api.telegram.org/file/bot{m.bot.token}/{file_path}"
            async with httpx.AsyncClient() as client:
                resp = await client.get(url)
                resp.raise_for_status()
                # Кросс-платформенный временный файл
                import tempfile, os
                fd, tmp_path = tempfile.mkstemp(suffix=".ogg")
                os.close(fd)
                with open(tmp_path, "wb") as f:
                    f.write(resp.content)
            answer_text = await transcribe_audio(tmp_path)
        except (ValueError, TypeError) as e:
            log_error(e, f"Data error transcribing audio for user {m.from_user.id}", user_id=m.from_user.id)
            answer_text = ""
        except (httpx.RequestError, OSError, IOError) as e:
            log_error(e, f"Unexpected error transcribing audio for user {m.from_user.id}", user_id=m.from_user.id)
            answer_text = ""
    else:
        return  # не текст и не voice — игнорируем

    # Сообщим пользователю, что идёт обработка ответа
    loading_msg = await m.answer("⏳ Обрабатываю ответ... подожди немного.")
    try:
        message_manager.add_message(m.from_user.id, loading_msg.message_id)
    except Exception:
        pass

    # Всегда используем LLM‑проверку (строковую похожесть не применяем, чтобы не засчитывать ложноположительно)
    answers = get_qa_answers(topic, idx)
    expected = answers[q_index] if q_index < len(answers) else ""
    try:
        is_correct, llm_feedback = await grade_theory_answer(
            topic=topic,
            question_text=question_text,
            student_answer=answer_text or "",
            expected_answer=expected or "",
        )
    finally:
        try:
            await loading_msg.delete()
        except (ValueError, TypeError) as e:
            log_error(e, f"Data error deleting loading message for user {m.from_user.id}", user_id=m.from_user.id)
        except (AttributeError, KeyError) as e:
            log_error(e, f"Unexpected error deleting loading message for user {m.from_user.id}", user_id=m.from_user.id)
    feedback = llm_feedback
    st["last_answer_correct"] = bool(is_correct)

    # Запоминаем результат для отслеживания ошибочных вопросов
    wrong_questions = st.setdefault("wrong_questions", {})
    all_answered = st.setdefault("all_answered", {})
    answered_questions = st.setdefault("answered_questions", {})  # key: "topic:idx" -> set of answered question indices
    
    # Добавляем текущий вопрос в список отвеченных
    answered_set = answered_questions.setdefault(key, set())
    answered_set.add(q_index)
    
    if not is_correct:
        # Добавляем в список ошибочных
        wrong_set = wrong_questions.setdefault(key, set())
        wrong_set.add(q_index)
    else:
        # Убираем из списка ошибочных (если был там)
        wrong_set = wrong_questions.get(key, set())
        wrong_set.discard(q_index)

    # Статистика по теме
    correct_before, total_before = get_theory_stats(m.from_user.id, topic)

    save_theory_task_answer(
        user_id=m.from_user.id,
        username=m.from_user.username or m.from_user.full_name or "",
        topic=topic,
        chunk_idx=idx,
        question_index=q_index,
        question_text=question_text,
        answer_text=answer_text or "",
        answer_type=answer_type or "text",
        voice_file_id=voice_file_id,
        is_correct=is_correct,
        feedback=feedback,
    )

    # Итоговая статистика, оценка и кнопки
    import math
    correct_after, total_questions = get_theory_stats(m.from_user.id, topic)

    # Пороговые значения
    t_satisf = max(1, math.ceil(0.3 * max(1, total_questions)))        # 30% и выше — удовлетворительно
    t_good   = max(1, math.floor(0.5 * max(1, total_questions)) + 1)   # >50%
    t_excell = max(1, math.floor(0.7 * max(1, total_questions)) + 1)   # >70%

    if correct_after >= t_excell:
        grade = "отлично"
        emoji = "🏆"
        next_label = ""
        to_next = 0
    elif correct_after >= t_good:
        grade = "хорошо"
        emoji = "💪"
        next_label = "отлично"
        to_next = max(0, t_excell - correct_after)
    elif correct_after >= t_satisf:
        grade = "удовлетворительно"
        emoji = "🙂"
        next_label = "хорошо"
        to_next = max(0, t_good - correct_after)
    else:
        grade = "неудовлетворительно!"
        emoji = "📚"
        next_label = "удовлетворительно"
        to_next = max(0, t_satisf - correct_after)

    # Текст похвалы/подсказки
    if is_correct:
        head = "Молодец! ✅ Ответ верный."
    else:
        head = "Не совсем верно. Попробуй ещё раз: нажми «🔁 Другой вопрос»."

    # Строка статуса с эмодзи и мотивацией
    base = f"Верно: {correct_after} из {total_questions}.\nТекущая оценка: {grade} {emoji}."
    if to_next > 0 and next_label:
        motivation = f" До оценки «{next_label}» осталось {to_next}. 🚀 Возьми ещё вопрос!"
    else:
        motivation = " Отличный прогресс! 🌟" if grade == "отлично" else " Хороший темп! ✨"
    stat_line = base + motivation

    full_msg = f"{head}\n\n{stat_line}"
    # Дополнительно: если по текущему кусочку все вопросы решены верно — похвалим и предложим перейти к следующей части
    solved_key = f"solved:{topic}:{idx}"
    solved_set: set[int] = st.setdefault(solved_key, set())
    if is_correct:
        solved_set.add(q_index)
    all_solved_here = len(solved_set) >= len(get_qa_questions(topic, idx)) and len(get_qa_questions(topic, idx)) > 0

    if not is_correct and expected and not all_solved_here:
        # Подсчитываем количество оставшихся вопросов в этом куске
        total_questions_in_chunk = len(get_qa_questions(topic, idx))
        wrong_set = wrong_questions.get(key, set())
        answered_set = answered_questions.get(key, set())
        
        # Считаем: неотвеченные + ошибочные
        unanswered = total_questions_in_chunk - len(answered_set)
        remaining_total = unanswered + len(wrong_set)
        
        # Формируем текст кнопки с количеством оставшихся вопросов
        if remaining_total > 0:
            button_text = f"🔁 Другой вопрос ({remaining_total})"
        else:
            button_text = "🔁 Другой вопрос"
        
        kb = InlineKeyboardMarkup(
            inline_keyboard=[[
                InlineKeyboardButton(text="💡 Показать образец ответа", callback_data="show_sample_answer"),
                InlineKeyboardButton(text=button_text, callback_data="learn_task_next"),
            ],
            [InlineKeyboardButton(text="↩️ К частям", callback_data="learn_to_parts")]]
        )
        sent = await m.answer(full_msg, reply_markup=kb)
        try:
            st["last_result_msg_id"] = sent.message_id
        except (ValueError, TypeError) as e:
            log_error(e, f"Data error setting last_result_msg_id for user {m.from_user.id}", user_id=m.from_user.id)
        except (AttributeError, KeyError) as e:
            log_error(e, f"Unexpected error setting last_result_msg_id for user {m.from_user.id}", user_id=m.from_user.id)
        try:
            message_manager.add_message(m.from_user.id, sent.message_id)
        except Exception:
            pass
    else:
        # При верном ответе показываем две кнопки: Ещё вопрос (в этом разделе) и К следующему разделу (следующий кусок)
        if all_solved_here:
            praise = "Отлично! ✅ Ты ответил(а) на все вопросы этой части. Готов двигаться дальше?"
            full_msg += f"\n\n{praise}"
            kb = InlineKeyboardMarkup(
                inline_keyboard=[[
                    InlineKeyboardButton(text="➡️ Перейти к следующей части", callback_data="learn_ok"),
                ],
                [InlineKeyboardButton(text="↩️ К частям", callback_data="learn_to_parts")]]
            )
        else:
            # Подсчитываем количество оставшихся вопросов в этом куске
            total_questions_in_chunk = len(get_qa_questions(topic, idx))
            wrong_set = wrong_questions.get(key, set())
            answered_set = answered_questions.get(key, set())
            
            # Считаем: неотвеченные + ошибочные
            unanswered = total_questions_in_chunk - len(answered_set)
            remaining_total = unanswered + len(wrong_set)
            
            # Если все вопросы отвечены правильно, убираем кнопку "Ещё вопрос"
            if remaining_total == 0:
                kb = InlineKeyboardMarkup(
                    inline_keyboard=[[
                        InlineKeyboardButton(text="➡️ К следующему разделу", callback_data="learn_ok"),
                    ],
                    [InlineKeyboardButton(text="↩️ К частям", callback_data="learn_to_parts")]]
                )
            else:
                # Формируем текст кнопки с количеством оставшихся вопросов
                button_text = f"🔄 Ещё вопрос ({remaining_total})"
                
                kb = InlineKeyboardMarkup(
                    inline_keyboard=[[
                        InlineKeyboardButton(text=button_text, callback_data="learn_task_next"),
                        InlineKeyboardButton(text="➡️ К следующему разделу", callback_data="learn_ok"),
                    ],
                    [InlineKeyboardButton(text="↩️ К частям", callback_data="learn_to_parts")]]
                )
        sent = await m.answer(full_msg, reply_markup=kb)
        try:
            st["last_result_msg_id"] = sent.message_id
        except (ValueError, TypeError) as e:
            log_error(e, f"Data error setting last_result_msg_id for user {m.from_user.id}", user_id=m.from_user.id)
        except (AttributeError, KeyError) as e:
            log_error(e, f"Unexpected error setting last_result_msg_id for user {m.from_user.id}", user_id=m.from_user.id)
        try:
            message_manager.add_message(m.from_user.id, sent.message_id)
        except Exception:
            pass

@router.callback_query(lambda c: c.data == "show_sample_answer")
async def show_sample_answer(cb: types.CallbackQuery):
    st = user_learning_state.get(cb.from_user.id)
    if not st:
        await cb.answer()
        return
    topic = st["topic"]
    idx = st["index"]
    assigned = st.get("assigned_tasks", {})
    key = f"{topic}:{idx}"
    q_index = assigned.get(key)
    answers = get_qa_answers(topic, idx)
    if q_index is None or not answers or q_index >= len(answers):
        await cb.message.answer("Образец ответа недоступен.")
    else:
        sent = await cb.message.answer(f"Образец ответа: {answers[q_index]}")
        try:
            message_manager.add_message(cb.from_user.id, sent.message_id)
        except Exception:
            pass
    await cb.answer()

# Кнопка показа ответа удалена по пожеланию

@router.callback_query(lambda c: c.data == "learn_to_chapters")
async def learn_to_chapters(cb: types.CallbackQuery):
    st = user_learning_state.get(cb.from_user.id)
    topic = st["topic"] if st else None
    user_learning_state.pop(cb.from_user.id, None)

    # Если состояние отсутствует (часто после «Стоп»), показываем бесплатные «Начала химии»
    if not topic:
        buttons = [
            [InlineKeyboardButton(text=t, callback_data=f"begin_topic_{i}")]
            for i, t in enumerate(BEGIN_CHEM_TOPICS)
        ]
        # Добавляем кнопку "В главное меню"
        buttons.append([InlineKeyboardButton(text="⬅️ В главное меню", callback_data="to_main_menu")])
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        sent = await cb.message.answer("Выбери главу из раздела «Начала химии»:", reply_markup=kb)
        try:
            message_manager.add_message(cb.from_user.id, sent.message_id)
        except Exception:
            pass
        await cb.answer()
        return

    if topic in BEGIN_CHEM_TOPICS:
        buttons = [
            [InlineKeyboardButton(text=t, callback_data=f"begin_topic_{i}")]
            for i, t in enumerate(BEGIN_CHEM_TOPICS)
        ]
        # Добавляем кнопку "В главное меню"
        buttons.append([InlineKeyboardButton(text="⬅️ В главное меню", callback_data="to_main_menu")])
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        await cb.message.answer("Выбери главу из раздела «Начала химии»:", reply_markup=kb)

    elif topic in ELEMENT_CHEM_TOPICS:
        from bot.services.plan import theory_allowed
        if not theory_allowed(cb.from_user.id, "elements"):
            msg = await cb.message.answer("Этот раздел доступен на тарифах ('Химия элементов', 'Самоподготовка', 'Групповые', 'Полный доступ'). Открой '💳 Тарифы и оплата'.", reply_markup=main_kb)
            try:
                message_manager.add_message(cb.from_user.id, msg.message_id)
            except Exception:
                pass
            await cb.answer()
            return
        buttons = [
            [InlineKeyboardButton(text=t, callback_data=f"element_topic_{i}")]
            for i, t in enumerate(ELEMENT_CHEM_TOPICS)
        ]
        # Добавляем кнопку "В главное меню"
        buttons.append([InlineKeyboardButton(text="⬅️ В главное меню", callback_data="to_main_menu")])
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        sent = await cb.message.answer("Выбери главу из раздела «Химия элементов»:", reply_markup=kb)
        try:
            message_manager.add_message(cb.from_user.id, sent.message_id)
        except Exception:
            pass

    else:
        from bot.services.plan import theory_allowed
        if not theory_allowed(cb.from_user.id, "organic"):
            msg = await cb.message.answer("Этот раздел доступен на тарифах ('Органика', 'Самоподготовка', 'Групповые', 'Полный доступ'). Открой '💳 Тарифы и оплата'.", reply_markup=main_kb)
            try:
                message_manager.add_message(cb.from_user.id, msg.message_id)
            except Exception:
                pass
            await cb.answer()
            return
        buttons = [
            [InlineKeyboardButton(text=t, callback_data=f"learn_topic_{i}")]
            for i, t in enumerate(LEARNING_TOPICS)
        ]
        # Добавляем кнопку "В главное меню"
        buttons.append([InlineKeyboardButton(text="⬅️ В главное меню", callback_data="to_main_menu")])
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        sent = await cb.message.answer("Выбери главу из раздела «Органическая химия»:", reply_markup=kb)
        try:
            message_manager.add_message(cb.from_user.id, sent.message_id)
        except Exception:
            pass

    await cb.answer()

# ================== ПОИСК ГЛАВ ==================
awaiting_topic_search: set[int] = set()

@router.message(lambda m: m.text == "🔎 Поиск главы")
async def search_topic_start(m: types.Message):
    awaiting_topic_search.add(m.from_user.id)
    await m.answer("🔎 Введи часть названия главы (например: «кислоты», «алканы», «связь», «ОВР»).")

@router.message(lambda m: m.from_user.id in awaiting_topic_search)
async def search_topic_query(m: types.Message):
    # снимаем ожидание
    awaiting_topic_search.discard(m.from_user.id)
    q = (m.text or "").strip().lower()
    if not q:
        await m.answer("Пустой запрос. Нажми «🔎 Поиск главы» и попробуй ещё раз.")
        return

    begin_matches = [(i, t) for i, t in enumerate(BEGIN_CHEM_TOPICS) if q in t.lower()]
    elem_matches  = [(i, t) for i, t in enumerate(ELEMENT_CHEM_TOPICS) if q in t.lower()]
    org_matches   = [(i, t) for i, t in enumerate(LEARNING_TOPICS)    if q in t.lower()]

    if not begin_matches and not org_matches and not elem_matches:
        await m.answer("Ничего не нашлось. Попробуй другое слово и нажми «🔎 Поиск главы».")
        return

    buttons: list[list[InlineKeyboardButton]] = []
    if begin_matches:
        buttons.append([InlineKeyboardButton(text="— Начала химии —", callback_data="noop")])
        buttons += [[InlineKeyboardButton(text=t, callback_data=f"begin_topic_{i}")] for i, t in begin_matches[:25]]

    if elem_matches:
        buttons.append([InlineKeyboardButton(text="— Химия элементов —", callback_data="noop")])
        buttons += [[InlineKeyboardButton(text=t, callback_data=f"element_topic_{i}")] for i, t in elem_matches[:25]]

    if org_matches:
        buttons.append([InlineKeyboardButton(text="— Органическая химия —", callback_data="noop")])
        buttons += [[InlineKeyboardButton(text=t, callback_data=f"learn_topic_{i}")] for i, t in org_matches[:25]]

    buttons.append([InlineKeyboardButton(text="⬅️ К разделам теории", callback_data="search_back_theory")])

    await m.answer(
        "Нашёл вот что — выбери главу:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )

@router.callback_query(lambda c: c.data == "search_back_theory")
async def search_back_theory(cb: types.CallbackQuery):
    rows = [
        [KeyboardButton(text="📖 Начала химии")],
        [KeyboardButton(text="⚗️ Химия элементов")],
        [KeyboardButton(text="🧬 Органическая химия")],
        [KeyboardButton(text="🔎 Поиск главы")],
        [KeyboardButton(text="⬅️ В меню")],
    ]
    kb = ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)
    await cb.message.answer("Выбери раздел теории:", reply_markup=kb)
    await cb.answer()

@router.callback_query(lambda c: c.data == "noop")
async def noop(cb: types.CallbackQuery):
    # декоративный разделитель
    await cb.answer()

# ================== Вопрос по теории ==================
@router.callback_query(lambda c: c.data == "learn_ask")
async def learn_ask(cb: types.CallbackQuery):
    from bot.services.plan import get_user_plan_code, limits_for, consume_daily
    plan = get_user_plan_code(cb.from_user.id)
    limit = limits_for(plan)["theory_ai_per_day"]
    ok, _left = consume_daily(cb.from_user.id, "theory_ai", limit)
    if not ok:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Тарифы и оплата", callback_data="to_tariffs")]
        ])
        await cb.message.answer("Лимит вопросов ИИ на сегодня исчерпан. Оформи подписку для безлимита.", reply_markup=kb)
        await cb.answer()
        return
    st = user_learning_state.get(cb.from_user.id)
    if st:
        st["awaiting_question"] = True
    await cb.message.answer("Напиши свой вопрос по этой главе:")

@router.message(lambda m: bool(user_learning_state.get(m.from_user.id, {}).get("awaiting_question")))
async def catch_user_question(m: types.Message):
    st = user_learning_state.get(m.from_user.id)
    if not st or not st.get("awaiting_question"):
        return
    st["awaiting_question"] = False
    topic = st["topic"]
    
    # Проверяем, что текст вопроса не пустой
    if not m.text or not m.text.strip():
        await m.answer("Пожалуйста, задайте вопрос текстом.")
        return
    
    # Ответ формирует реальная функция из gpt_service.py
    answer = await answer_student_question(topic, m.text.strip())
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="❓ Ещё вопрос ИИ", callback_data="learn_ask"),
            InlineKeyboardButton(text="➡️ К сл. разделу", callback_data="learn_ok"),
        ]]
    )
    await m.answer(answer, reply_markup=kb)
