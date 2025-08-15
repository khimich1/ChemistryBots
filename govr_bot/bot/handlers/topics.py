from aiogram import Router, types
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
    BufferedInputFile,
)
from aiogram.enums import ParseMode

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
    get_audio_from_db,
)
from bot.handlers.menu import main_kb
from bot.services.gpt_service import answer_student_question

router = Router()

# ================== Разделы «Теории по химии» ==================

# 1) Начала химии — список глав
@router.message(lambda m: m.text == "📖 Начала химии")
async def begin_chem(m: types.Message):
    buttons = [
        [InlineKeyboardButton(text=topic, callback_data=f"begin_topic_{i}")]
        for i, topic in enumerate(BEGIN_CHEM_TOPICS)
    ]
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await m.answer("Выбери главу из раздела «Начала химии»:", reply_markup=kb)

# Выбор главы «Начала химии»
@router.callback_query(lambda c: c.data.startswith("begin_topic_"))
async def begin_topic_chosen(cb: types.CallbackQuery, bot):
    try:
        idx = int(cb.data.split("begin_topic_")[-1])
        topic = BEGIN_CHEM_TOPICS[idx]
    except Exception:
        await cb.message.answer("Не получилось определить тему. Попробуй ещё раз.", reply_markup=main_kb)
        return
    user_learning_state[cb.from_user.id] = {"topic": topic, "index": 0, "awaiting_question": False}
    await send_next_chunk(cb.from_user.id, bot)

# 2) Химия элементов — СПИСОК ГЛАВ (полноценный)
@router.message(lambda m: m.text == "⚗️ Химия элементов")
async def element_chem(m: types.Message):
    buttons = [
        [InlineKeyboardButton(text=topic, callback_data=f"element_topic_{i}")]
        for i, topic in enumerate(ELEMENT_CHEM_TOPICS)
    ]
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await m.answer("Выбери главу из раздела «Химия элементов»:", reply_markup=kb)

# Выбор главы «Химия элементов»
@router.callback_query(lambda c: c.data.startswith("element_topic_"))
async def element_topic_chosen(cb: types.CallbackQuery, bot):
    try:
        idx = int(cb.data.split("element_topic_")[-1])
        topic = ELEMENT_CHEM_TOPICS[idx]
    except Exception:
        await cb.message.answer("Не получилось определить тему. Попробуй ещё раз.", reply_markup=main_kb)
        return
    user_learning_state[cb.from_user.id] = {"topic": topic, "index": 0, "awaiting_question": False}
    await send_next_chunk(cb.from_user.id, bot)

# 3) Органическая химия — список глав
@router.message(lambda m: m.text == "🧬 Органическая химия")
async def organic_chem(m: types.Message):
    buttons = [
        [InlineKeyboardButton(text=topic, callback_data=f"learn_topic_{i}")]
        for i, topic in enumerate(LEARNING_TOPICS)
    ]
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await m.answer("Выбери главу из раздела «Органическая химия»:", reply_markup=kb)

# Выбор главы «Органическая химия»
@router.callback_query(lambda c: c.data.startswith("learn_topic_"))
async def learn_topic_chosen(cb: types.CallbackQuery, bot):
    try:
        idx = int(cb.data.split("learn_topic_")[-1])
        topic = LEARNING_TOPICS[idx]
    except Exception:
        await cb.message.answer("Не получилось определить тему. Попробуй ещё раз.", reply_markup=main_kb)
        return
    user_learning_state[cb.from_user.id] = {"topic": topic, "index": 0, "awaiting_question": False}
    await send_next_chunk(cb.from_user.id, bot)

# ================== Универсальный показ следующего chunk ==================
async def send_next_chunk(user_id: int, bot):
    st = user_learning_state.get(user_id)
    if not st:
        return

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

    # Проверяем наличие аудио для этого фрагмента
    audio_data = get_audio_from_db(topic, idx)
    has_audio = audio_data is not None

    # Создаем клавиатуру с кнопкой аудио если есть аудио
    keyboard_buttons = [
        [
            InlineKeyboardButton(text="◀️ Назад", callback_data="learn_back"),
            InlineKeyboardButton(text="Далее", callback_data="learn_ok"),
        ],
        [
            InlineKeyboardButton(text="❓ Есть вопрос", callback_data="learn_ask"),
            InlineKeyboardButton(text="■ Стоп", callback_data="learn_stop"),
            InlineKeyboardButton(text="🏠 К главам", callback_data="learn_to_chapters"),
        ],
    ]
    
    # Добавляем кнопку аудио если есть аудио
    if has_audio:
        keyboard_buttons.insert(1, [
            InlineKeyboardButton(text="🔊 Слушать аудио", callback_data="learn_audio")
        ])

    kb = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

    await bot.send_message(
        user_id,
        header + formatted,
        reply_markup=kb,
        parse_mode=ParseMode.MARKDOWN,
    )

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
        await bot.send_voice(
            chat_id=cb.from_user.id,
            voice=BufferedInputFile(
                audio_blob, 
                filename=f"{topic}_chunk_{idx}.{audio_format}"
            ),
            caption=f"🔊 Аудио к фрагменту «{topic}» (часть {idx+1})"
        )
        await cb.answer("Аудио отправлено!")
        
    except Exception as e:
        await cb.answer(f"Ошибка отправки аудио: {str(e)}")

@router.callback_query(lambda c: c.data == "learn_to_chapters")
async def learn_to_chapters(cb: types.CallbackQuery):
    st = user_learning_state.get(cb.from_user.id)
    topic = st["topic"] if st else None
    user_learning_state.pop(cb.from_user.id, None)

    if topic in BEGIN_CHEM_TOPICS:
        buttons = [
            [InlineKeyboardButton(text=t, callback_data=f"begin_topic_{i}")]
            for i, t in enumerate(BEGIN_CHEM_TOPICS)
        ]
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        await cb.message.answer("Выбери главу из раздела «Начала химии»:", reply_markup=kb)

    elif topic in ELEMENT_CHEM_TOPICS:
        buttons = [
            [InlineKeyboardButton(text=t, callback_data=f"element_topic_{i}")]
            for i, t in enumerate(ELEMENT_CHEM_TOPICS)
        ]
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        await cb.message.answer("Выбери главу из раздела «Химия элементов»:", reply_markup=kb)

    else:
        buttons = [
            [InlineKeyboardButton(text=t, callback_data=f"learn_topic_{i}")]
            for i, t in enumerate(LEARNING_TOPICS)
        ]
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        await cb.message.answer("Выбери главу из раздела «Органическая химия»:", reply_markup=kb)

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
    st = user_learning_state.get(cb.from_user.id)
    if st:
        st["awaiting_question"] = True
    await cb.message.answer("Напиши свой вопрос по этой главе:")

@router.message()
async def catch_user_question(m: types.Message):
    st = user_learning_state.get(m.from_user.id)
    if not st or not st.get("awaiting_question"):
        return
    st["awaiting_question"] = False
    topic = st["topic"]
    # Ответ формирует реальная функция из gpt_service.py
    answer = await answer_student_question(topic, m.text)
    await m.answer(answer)
