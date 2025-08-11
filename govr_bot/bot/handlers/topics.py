import os
import sqlite3
from aiogram import Router, types
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.enums import ParseMode
from bot.handlers.menu import main_kb
from bot.utils import (
    ALL_TOPICS, clean_html, user_topics, LEARNING_TOPICS,
    user_learning_state, TEXTBOOK_CONTENT, latex_to_codeblock
)
from bot.services.gpt_service import (
    classify_topic, analyze_answer, transcribe_audio,
    teach_material, answer_student_question
)
from bot.services.spreadsheet import save_answer

router = Router()

# --- ДОБАВЛЕНА ФУНКЦИЯ ДЛЯ БЫСТРОГО ПОЛУЧЕНИЯ ЛЕКЦИИ ИЗ БАЗЫ ---
def get_prepared_lecture(topic, idx):
    """
    Получает готовую лекцию из базы по теме и номеру chunk'а.
    Возвращает текст лекции, либо None если не найдено.
    """
    with sqlite3.connect("prepared_lectures.db") as conn:
        c = conn.cursor()
        c.execute("SELECT lecture FROM prepared_lectures WHERE topic=? AND chunk_idx=?", (topic, idx))
        row = c.fetchone()
        return row[0] if row else None

# --- Клавиатуры для обычных тем ---
topics_kb = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text=ALL_TOPICS[i]),
            KeyboardButton(text=ALL_TOPICS[i+1] if i+1 < len(ALL_TOPICS) else "")
        ]
        for i in range(0, len(ALL_TOPICS), 2)
    ] + [[KeyboardButton(text="⬅️ В меню")]],
    resize_keyboard=True,
    one_time_keyboard=True
)

after_topic_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="⬅️ К темам"), KeyboardButton(text="⬅️ В меню")]
    ],
    resize_keyboard=True
)

choose_chapter_kb = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="⬅️ В меню")]],
    resize_keyboard=True
)

# === 1. Обычные темы ===
@router.message(lambda m: m.text == "🧪 Устный зачет")
async def show_topics(m: types.Message):
    await m.answer("Выберите тему по органической химии:", reply_markup=topics_kb)

@router.message(lambda m: m.text in ALL_TOPICS)
async def ask_questions(m: types.Message):
    user_topics[m.from_user.id] = m.text
    questions = (
        f"1. Общая характеристика класса {m.text}\n"
        f"2. Способы получения {m.text}\n"
        f"3. Химические свойства {m.text}"
    )
    await m.answer(questions, reply_markup=after_topic_kb)
    await m.answer("Запишите голосовой ответ на эти вопросы:")

@router.message(lambda m: m.text == "⬅️ К темам")
async def back_to_topics(m: types.Message):
    await m.answer("Выберите тему по органической химии:", reply_markup=topics_kb)

@router.message(lambda m: m.text == "⬅️ В меню")
async def back_to_menu(m: types.Message):
    await m.answer("Главное меню:", reply_markup=main_kb)

# === 2. Курс по органике ===

@router.message(lambda m: m.text == "🌱 Курс по органике")
async def on_learning_start(m: types.Message):
    buttons = [
        [InlineKeyboardButton(text=topic, callback_data=f"learn_topic_{i}")]
        for i, topic in enumerate(LEARNING_TOPICS)
    ]
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await m.answer(
        "Выберите главу для курса по органике:",
        reply_markup=kb
    )
    await m.answer(
        "Можешь в любой момент вернуться в меню:",
        reply_markup=choose_chapter_kb
    )

@router.callback_query(lambda c: c.data.startswith("learn_topic_"))
async def on_topic_chosen(cb: types.CallbackQuery, bot):
    idx = int(cb.data.split("learn_topic_")[-1])
    topic = LEARNING_TOPICS[idx]
    user_learning_state[cb.from_user.id] = {"topic": topic, "index": 0, "awaiting_question": False}
    await send_next_chunk(cb.from_user.id, bot)

# --- ГЛАВНОЕ ИЗМЕНЕНИЕ ---
async def send_next_chunk(user_id: int, bot):
    """
    Показывает следующий chunk теории пользователю.
    Теперь лекция берётся из базы (а не генерируется каждый раз через GPT)!
    """
    st = user_learning_state.get(user_id)
    if not st:
        return
    topic = st["topic"]
    idx = st["index"]
    chunks = TEXTBOOK_CONTENT.get(topic, [])
    total = len(chunks)
    chap_num = LEARNING_TOPICS.index(topic) + 1
    chap_total = len(LEARNING_TOPICS)
    if idx >= total:
        await bot.send_message(
            user_id,
            f"Глава {topic} пройдена! 🎉\nВозвращаю меню.",
            reply_markup=main_kb
        )
        user_learning_state.pop(user_id, None)
        return

    header = f"Глава {chap_num}/{chap_total}, порция {idx+1}/{total}\n\n"

    # --- БЫЛО ---
    # raw = await teach_material(chunks[idx])
    # --- СТАЛО ---
    raw = get_prepared_lecture(topic, idx)
    if not raw:
        await bot.send_message(user_id, "Лекция пока не подготовлена. Обратитесь к администратору.")
        return

    formatted = latex_to_codeblock(raw)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="◀️ Назад", callback_data="learn_back"),
            InlineKeyboardButton(text="👍 Понятно", callback_data="learn_ok")
        ],
        [
            InlineKeyboardButton(text="❓ Есть вопрос", callback_data="learn_ask"),
            InlineKeyboardButton(text="■ Стоп", callback_data="learn_stop"),
            InlineKeyboardButton(text="🏠 К главам", callback_data="learn_to_chapters")
        ]
    ])
    await bot.send_message(
        user_id,
        header + formatted,
        reply_markup=kb,
        parse_mode=ParseMode.MARKDOWN
    )

@router.callback_query(lambda c: c.data == "learn_ok")
async def on_learning_ok(cb: types.CallbackQuery, bot):
    st = user_learning_state.get(cb.from_user.id)
    if not st:
        return
    st["index"] += 1
    await send_next_chunk(cb.from_user.id, bot)

@router.callback_query(lambda c: c.data == "learn_back")
async def on_learning_back(cb: types.CallbackQuery, bot):
    st = user_learning_state.get(cb.from_user.id)
    if not st:
        return
    if st["index"] == 0:
        await cb.answer("Вы на первой порции.", show_alert=True)
    else:
        st["index"] -= 1
        await send_next_chunk(cb.from_user.id, bot)

@router.callback_query(lambda c: c.data == "learn_ask")
async def on_learning_ask(cb: types.CallbackQuery, bot):
    st = user_learning_state.get(cb.from_user.id)
    if not st:
        return
    st["awaiting_question"] = True
    await bot.send_message(cb.from_user.id, "Задайте ваш вопрос по этому материалу:", reply_markup=ReplyKeyboardRemove())

@router.callback_query(lambda c: c.data == "learn_stop")
async def on_learning_stop(cb: types.CallbackQuery, bot):
    user_learning_state.pop(cb.from_user.id, None)
    await bot.send_message(
        cb.from_user.id,
        "Курс остановлен. Чтобы возобновить, нажми ▶️ Продолжить или выбери 🌱 Курс по органике.",
        reply_markup=main_kb
    )

@router.callback_query(lambda c: c.data == "learn_to_chapters")
async def to_chapters(cb: types.CallbackQuery, bot):
    buttons = [
        [InlineKeyboardButton(text=topic, callback_data=f"learn_topic_{i}")]
        for i, topic in enumerate(LEARNING_TOPICS)
    ]
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    user_learning_state.pop(cb.from_user.id, None)
    await bot.send_message(cb.from_user.id, "Выберите главу для курса по органике:", reply_markup=kb)
    await bot.send_message(cb.from_user.id, "Можешь в любой момент вернуться в меню:", reply_markup=choose_chapter_kb)


# === Работа с голосом и текстом для любого режима ===
@router.message(lambda m: m.voice is not None)
async def on_voice(m: types.Message, bot):
    file = await bot.get_file(m.voice.file_id)
    path = f"audio_{m.from_user.id}.ogg"
    await bot.download_file(file.file_path, path)
    try:
        txt = await transcribe_audio(path)
        st = user_learning_state.get(m.from_user.id)
        if st and st.get("awaiting_question"):
            answer = await answer_student_question(st["topic"], txt.strip())
            st["awaiting_question"] = False
            st["index"] += 1
            await m.answer(answer)
            await send_next_chunk(m.from_user.id, bot)
        else:
            await process_answer(m, txt.strip())
    finally:
        os.remove(path)

@router.message(lambda m: m.text and not m.text.startswith("/"))
async def on_text(m: types.Message, bot):
    st = user_learning_state.get(m.from_user.id)
    if st and st.get("awaiting_question"):
        await on_student_question(m, bot)
    else:
        await process_answer(m, m.text.strip())

async def process_answer(m: types.Message, transcript: str):
    uid = m.from_user.id
    topic = user_topics.pop(uid, None) or await classify_topic(transcript)
    ctx = "\n\n".join(TEXTBOOK_CONTENT.get(topic, [])[:3])
    feedback = await analyze_answer(transcript, topic, ctx)
    clean = clean_html(feedback)
    save_answer(uid, m.from_user.full_name, topic, transcript, clean)
    from bot.handlers.menu import main_kb
    await m.answer(
        f"📘 Тема: <b>{topic}</b>\n"
        f"📝 Ответ: {transcript}\n\n"
        f"💬 Комментарий:\n{clean}",
        reply_markup=main_kb
    )

@router.message(lambda m: m.text and m.from_user.id in user_learning_state and user_learning_state[m.from_user.id].get("awaiting_question"))
async def on_student_question(m: types.Message, bot):
    st = user_learning_state[m.from_user.id]
    topic = st["topic"]
    answer = await answer_student_question(topic, m.text.strip())
    st["awaiting_question"] = False
    st["index"] += 1
    await m.answer(answer)
    await send_next_chunk(m.from_user.id, bot)

@router.message(lambda m: m.text == "▶️ Продолжить")
async def resume_course(m: types.Message):
    # Проверяем, есть ли сохранённое состояние курса для пользователя
    state = user_learning_state.get(m.from_user.id)
    if not state:
        await m.answer("Ты ещё не начинал курс. Выбери 'Курс по органике' для старта.", reply_markup=main_kb)
        return
    # Если состояние есть — показываем следующий chunk
    from bot.handlers.topics import send_next_chunk  # импорт функции показа следующей порции
    await send_next_chunk(m.from_user.id, m.bot)