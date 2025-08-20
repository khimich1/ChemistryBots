from aiogram import Router, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.filters import Command
import html  # Стандартная библиотека для экранирования HTML
import re

# --- Импортируем все функции работы с базой ---
from bot.services.answer_db import (
    save_test_answer,
    save_test_progress,
    load_test_progress,
    clear_test_progress,
    get_mistake_questions,
    set_answer_correct,
    log_question_started,
    log_question_answered,
    get_user_full_name,
    save_test_debug,
)
from bot.services.test_sql import get_all_tests_types, get_questions_by_type, get_question_by_id, mark_question_issue

from bot.handlers.menu import main_kb  # Импорт клавиатуры главного меню

router = Router()
user_test_state = {}

# Небольшое форматирование текста задания: переносы строк перед А), Б), В), Г)
# и выделение заголовков типа "Реагенты:" / "Продукты:" на отдельную строку.
def _format_question_text(text: str) -> str:
    if not isinstance(text, str):
        return ""
    s = text.strip()

    # Заголовки на отдельной строке
    def _hdr(m):
        return "\n" + m.group(1)
    s = re.sub(r"\s*(Реагенты:)", _hdr, s)
    s = re.sub(r"\s*(Продукты:)", _hdr, s)
    s = re.sub(r"\s*(Продукт:)", _hdr, s)
    s = re.sub(r"\s*(Продукт реакции:)", _hdr, s)
    s = re.sub(r"\s*(Продукты электролиза:)", _hdr, s)

    # Переносы перед пунктами А) Б) В) Г) Д) Е) и латинскими A) B) C) D) E)
    def _letter_bullet(m):
        return "\n" + m.group(1).lower() + ") "
    s = re.sub(r"(?<!\n)\s*([АБВГДЕ])\)", _letter_bullet, s)
    s = re.sub(r"(?<!\n)\s*([A-E])\)", _letter_bullet, s)

    # Убираем лишние множественные пустые строки
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s

# Рендер обычного текста с поддержкой блоков кода в тройных кавычках ```...```
# Вне блоков — безопасное HTML-экранирование; внутри — <pre>...</pre>
def _to_html_with_code(text: str) -> str:
    if not isinstance(text, str) or not text:
        return ""
    parts = re.split(r"```([\s\S]*?)```", text)
    out: list[str] = []
    for idx, chunk in enumerate(parts):
        if idx % 2 == 0:
            out.append(html.escape(chunk))
        else:
            out.append("<pre>" + html.escape(chunk.strip()) + "</pre>")
    return "".join(out)

# =========================
# 1. Клавиатура для выбора тестов
# =========================
def get_tests_types_kb(with_menu=False):
    types = get_all_tests_types()
    keyboard = [
        [InlineKeyboardButton(text=f"Тест {t}", callback_data=f"choose_test_{t}")]
        for t in types if t not in (None, '')
    ]
    # --- Кнопка "Работа над ошибками"
    keyboard.append([InlineKeyboardButton(text="💡 Работа над ошибками", callback_data="work_on_mistakes")])
    if with_menu:
        keyboard.append([InlineKeyboardButton(text="⬅️ В главное меню", callback_data="to_main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

# =========================
# 2. Клавиатура для вопроса теста: Подсказка и Стоп тест
# =========================
def get_stop_test_kb(q_id, hints_left: int | None = None):
    hint_text = "💡 Подсказка" if hints_left is None else f"💡 Подсказка ({hints_left})"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=hint_text, callback_data=f"hint_{q_id}")],
            [InlineKeyboardButton(text="⏹️ Стоп тест", callback_data="stop_test")],
            [InlineKeyboardButton(text="❗ Пожаловаться", callback_data=f"report_{q_id}")]
        ]
    )

# Клавиатура для подсказки: кнопка «К заданию» удаляет сообщение с подсказкой
def get_hint_kb(q_id: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ К заданию", callback_data=f"back_to_question_{q_id}")]
        ]
    )

# Кнопка «Объяснение» к сообщению с результатом
def get_result_kb(q_id: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🧠 Объяснение", callback_data=f"explain_{q_id}")],
                         [InlineKeyboardButton(text="➡️ Далее", callback_data=f"next_q_{q_id}")]]
    )

# Кнопка «Далее» одиночная (для показа под объяснением)
def get_next_kb(q_id: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="➡️ Далее", callback_data=f"next_q_{q_id}")]]
    )

# Клавиатура только с «Объяснение» (после нажатия «Далее» на результате)
def get_explain_only_kb(q_id: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🧠 Объяснение", callback_data=f"explain_{q_id}")]]
    )

# =========================
# 3. Показываем меню тестов
# =========================
@router.message(lambda m: m.text == "📝 Тесты")
async def show_tests_types_menu(m: types.Message):
    await m.answer("Выбери номер теста:", reply_markup=get_tests_types_kb())

@router.message(Command("tests"))
async def show_tests_menu_cmd(m: types.Message):
    await show_tests_types_menu(m)

# =========================
# 4. Начать тест (по callback-кнопке) с проверкой прогресса
# =========================
@router.callback_query(lambda c: c.data.startswith("choose_test_"))
async def start_test(cb: CallbackQuery):
    try:
        test_type = int(cb.data.split("_")[-1])
    except ValueError:
        await cb.answer("Ошибка: неверный номер теста.")
        return

    idx, q_ids = load_test_progress(cb.from_user.id, test_type)
    if idx is not None and q_ids:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="▶️ Продолжить", callback_data=f"continue_test_{test_type}")],
                [InlineKeyboardButton(text="🔄 Начать заново", callback_data=f"restart_test_{test_type}")]
            ]
        )
        await cb.message.answer(
            f"Вы уже проходили этот тест. Продолжить с вопроса {idx+1} или начать заново?",
            reply_markup=kb
        )
        await cb.answer()
        return

    # --- Если прогресса нет — стандартное поведение ---
    questions = get_questions_by_type(test_type)
    if not questions:
        await cb.message.answer("Нет вопросов для этого теста.")
        await cb.answer()
        return
    user_test_state[cb.from_user.id] = {
        "type": test_type,
        "idx": 0,
        "q_ids": [q["id"] for q in questions]
    }
    clear_test_progress(cb.from_user.id, test_type)
    await send_next_test_question(cb.from_user.id, cb.message, is_callback=True)
    await cb.answer()

@router.callback_query(lambda c: c.data.startswith("explain_"))
async def show_explanation(cb: CallbackQuery):
    q_id = int(cb.data.split("_")[-1])
    q = get_question_by_id(q_id)
    explanation = q.get("explanation", "") or q.get("detailed_explanation", "")
    if explanation and explanation.strip():
        await cb.message.answer(
            _to_html_with_code(f"🧠 Объяснение:\n{explanation}"),
            parse_mode="HTML",
            reply_markup=get_next_kb(q_id)
        )
    else:
        await cb.message.answer("Пока нет объяснения к этому заданию.")
    await cb.answer()

# =========================
# 11. Переход к следующему вопросу по кнопке «Далее»
# =========================
@router.callback_query(lambda c: c.data.startswith("next_q_"))
async def go_next_question(cb: CallbackQuery):
    # Если «Далее» нажали под объяснением — удаляем сообщение объяснения.
    # Если под карточкой результата — оставляем карточку и убираем кнопку «Далее».
    try:
        parts = cb.data.split("_")
        q_id = int(parts[-1]) if parts and parts[-1].isdigit() else None
        msg_text = (cb.message.text or "").strip()
        is_explanation = msg_text.startswith("🧠 Объяснение")
        if is_explanation:
            try:
                await cb.message.delete()
            except Exception:
                # если не удалилось — хотя бы скрыть клавиатуру
                try:
                    await cb.message.edit_reply_markup(reply_markup=None)
                except Exception:
                    pass
        else:
            if q_id:
                try:
                    await cb.message.edit_reply_markup(reply_markup=get_explain_only_kb(q_id))
                except Exception:
                    pass
    except Exception:
        pass

    st = user_test_state.get(cb.from_user.id)
    if not st:
        await cb.answer()
        return

    # Если это обычный тест (есть q_ids)
    if "q_ids" in st:
        # Удаляем старый вопрос, чтобы в ленте оставались только результаты
        try:
            last_q_id = st.pop("last_question_msg_id", None)
            if last_q_id:
                await cb.message.bot.delete_message(chat_id=cb.message.chat.id, message_id=last_q_id)
        except Exception:
            pass
        st["idx"] += 1
        await send_next_test_question(cb.from_user.id, cb.message, is_callback=True)
        await cb.answer()
        return

    # Если это режим ошибок
    if "mistake_q_ids" in st:
        try:
            last_q_id = st.pop("last_question_msg_id", None)
            if last_q_id:
                await cb.message.bot.delete_message(chat_id=cb.message.chat.id, message_id=last_q_id)
        except Exception:
            pass
        st["idx"] += 1
        await send_next_mistake_question(cb.from_user.id, cb.message)
        await cb.answer()
        return

    await cb.answer()

# --- Продолжить тест ---
@router.callback_query(lambda c: c.data.startswith("continue_test_"))
async def continue_test(cb: CallbackQuery):
    test_type = int(cb.data.split("_")[-1])
    idx, q_ids = load_test_progress(cb.from_user.id, test_type)
    if idx is not None and q_ids:
        user_test_state[cb.from_user.id] = {
            "type": test_type,
            "idx": idx,
            "q_ids": q_ids
        }
        await send_next_test_question(cb.from_user.id, cb.message, is_callback=True)
    else:
        await cb.message.answer("Не удалось найти сохранённый прогресс. Попробуйте начать заново.")
    await cb.answer()

# =========================
# 5.1 Жалоба на вопрос
# =========================
@router.callback_query(lambda c: c.data.startswith("report_"))
async def report_question(cb: CallbackQuery):
    q_id = int(cb.data.split("_")[-1])
    # Пытаемся удалить сообщение-вопрос сразу при нажатии «Пожаловаться»
    try:
        st = user_test_state.get(cb.from_user.id) or {}
        last_q_id = st.pop("last_question_msg_id", None)
        if last_q_id:
            await cb.message.bot.delete_message(chat_id=cb.message.chat.id, message_id=last_q_id)
    except Exception:
        pass
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📝 Проблема с заданием", callback_data=f"report_reason_{q_id}_task")],
            [InlineKeyboardButton(text="💡 Проблема с подсказкой", callback_data=f"report_reason_{q_id}_hint")],
            [InlineKeyboardButton(text="✅ Проблема с ответом", callback_data=f"report_reason_{q_id}_answer")],
            [InlineKeyboardButton(text="✍️ Свой вариант", callback_data=f"report_reason_{q_id}_custom")],
        ]
    )
    await cb.message.answer("Что именно смутило в этом задании?", reply_markup=kb)
    await cb.answer()


@router.callback_query(lambda c: c.data.startswith("report_reason_"))
async def report_reason(cb: CallbackQuery):
    parts = cb.data.split("_")
    # ['report', 'reason', '{q_id}', '{code}']
    q_id = int(parts[2])
    code = parts[3]
    reason_map = {
        "task": "Проблема с заданием",
        "hint": "Проблема с подсказкой",
        "answer": "Проблема с ответом",
    }
    if code == "custom":
        # Просим текст причины в свободной форме
        st = user_test_state.get(cb.from_user.id) or {}
        st["awaiting_issue_text"] = {"q_id": q_id}
        user_test_state[cb.from_user.id] = st
        await cb.message.answer("Опиши проблему коротко текстом. Этот вопрос мы больше не покажем до исправления.")
        await cb.answer()
        return

    # Фиксируем и скрываем вопрос глобально
    reason_text = reason_map.get(code)
    mark_question_issue(q_id, reason_text)
    # Логируем в test_debug (status: не решено)
    save_test_debug(q_id, reason_text or "", status="не решено")
    await cb.message.answer("Спасибо! Отметил проблему и убрал вопрос из выдачи до исправления.")

    # Продолжаем тест, пропуская этот вопрос
    st = user_test_state.get(cb.from_user.id)
    if not st:
        await cb.answer()
        return
    if "mistake_q_ids" in st:
        # режим работы над ошибками: удаляем текущий id из списка и показываем следующий
        try:
            st["mistake_q_ids"].remove(q_id)
        except ValueError:
            pass
        user_test_state[cb.from_user.id] = st
        await send_next_mistake_question(cb.from_user.id, cb.message)
    else:
        # обычный режим: двигаем индекс
        st["idx"] = st.get("idx", 0) + 1
        user_test_state[cb.from_user.id] = st
        await send_next_test_question(cb.from_user.id, cb.message, is_callback=True)
    await cb.answer()


# =========================
# 5.2 Обработчик текста причины (свой вариант)
# =========================
@router.message(lambda m: (
    m.from_user.id in user_test_state
    and isinstance(getattr(m, "text", None), str)
    and user_test_state[m.from_user.id].get("awaiting_issue_text") is not None
))
async def report_custom_text(m: types.Message):
    st = user_test_state.get(m.from_user.id) or {}
    data = st.pop("awaiting_issue_text", None) or {}
    q_id = int(data.get("q_id")) if data.get("q_id") is not None else None
    reason = (m.text or "").strip()
    if q_id is not None:
        mark_question_issue(q_id, reason)
        save_test_debug(q_id, reason or "", status="не решено")
        await m.answer("Спасибо за подробности! Вопрос скрыт до исправления.")
    else:
        await m.answer("Спасибо! Записал жалобу.")

    # Продолжаем тест
    if "mistake_q_ids" in st and q_id is not None:
        try:
            st["mistake_q_ids"].remove(q_id)
        except ValueError:
            pass
        user_test_state[m.from_user.id] = st
        await send_next_mistake_question(m.from_user.id, m)
    else:
        st["idx"] = st.get("idx", 0) + 1
        user_test_state[m.from_user.id] = st
        await send_next_test_question(m.from_user.id, m)

# --- Начать тест заново ---
@router.callback_query(lambda c: c.data.startswith("restart_test_"))
async def restart_test(cb: CallbackQuery):
    test_type = int(cb.data.split("_")[-1])
    questions = get_questions_by_type(test_type)
    if not questions:
        await cb.message.answer("Нет вопросов для этого теста.")
        await cb.answer()
        return
    user_test_state[cb.from_user.id] = {
        "type": test_type,
        "idx": 0,
        "q_ids": [q["id"] for q in questions]
    }
    clear_test_progress(cb.from_user.id, test_type)
    await send_next_test_question(cb.from_user.id, cb.message, is_callback=True)
    await cb.answer()

# =========================
# 5. Отправить следующий вопрос теста
# =========================
async def send_next_test_question(user_id, message_obj, is_callback=False):
    state = user_test_state.get(user_id)
    if not state:
        return
    idx = state["idx"]
    q_ids = state["q_ids"]
    if idx >= len(q_ids):
        user_test_state.pop(user_id, None)
        await message_obj.answer("Тест завершён! Возвращаюсь в меню.")
        return
    q = get_question_by_id(q_ids[idx])
    log_question_started(user_id, state["type"], q["id"])  # --- ЛОГИРОВАНИЕ СТАРТА ---
    options = q['options'].split('\n')
    formatted_q = _format_question_text(q['question'])
    msg = (
        f"Вопрос {idx+1} из {len(q_ids)} (Тест {state['type']})\n\n"
        f"{formatted_q}\n\n" +
        "\n".join([f"{i+1}. {opt}" for i, opt in enumerate(options)]) +
        "\n\nВведите номер(а) ответа (например: 2 или 13):"
    )
    # Подсказки: максимум 10 на 30 вопросов одного теста
    # Считаем, сколько подсказок уже использовано в текущем тесте
    used_hints = user_test_state.get(user_id, {}).get("used_hints", {}).get(state["type"], 0)
    hints_left = max(0, 10 - used_hints)
    kb = get_stop_test_kb(q['id'], hints_left=hints_left)
    sent_q = await message_obj.answer(_to_html_with_code(msg), parse_mode="HTML", reply_markup=kb)
    # Запомним id сообщения-вопроса, чтобы удалить его при переходе «Далее»
    user_test_state[user_id]["last_question_msg_id"] = sent_q.message_id

# =========================
# 6. Обработчик: Стоп тест (универсально для обоих режимов)
# =========================
@router.callback_query(lambda c: c.data == "stop_test")
async def stop_test(cb: CallbackQuery):
    state = user_test_state.pop(cb.from_user.id, None)
    # --- Если работаем над ошибками ---
    if state and "mistake_q_ids" in state:
        await cb.message.answer(
            "Разбор ошибок завершён! Возвращаюсь в раздел тестов.",
            reply_markup=get_tests_types_kb(with_menu=True)
        )
    elif state:
        save_test_progress(cb.from_user.id, state["type"], state["idx"], state["q_ids"])
        await cb.message.answer(
            "Тест прерван! Выбери тест для прохождения:",
            reply_markup=get_tests_types_kb(with_menu=True)
        )
    else:
        await cb.message.answer(
            "Действие отменено. Выбери тест:",
            reply_markup=get_tests_types_kb(with_menu=True)
        )
    await cb.answer()

# =========================
# 7. Обработчик кнопки возврата в главное меню
# =========================
@router.callback_query(lambda c: c.data == "to_main_menu")
async def to_main_menu(cb: CallbackQuery):
    await cb.message.answer("Главное меню:", reply_markup=main_kb)
    await cb.answer()

# =========================
# 8. Подсказка к вопросу
# =========================
@router.callback_query(lambda c: c.data.startswith("hint_"))
async def show_hint(cb: CallbackQuery):
    q_id = int(cb.data.split("_")[-1])
    q = get_question_by_id(q_id)
    # Подсказки: проверяем лимит 10 на тест (30 вопросов)
    st = user_test_state.get(cb.from_user.id)
    test_type = st.get("type") if st else None
    used_map = user_test_state.setdefault(cb.from_user.id, {}).setdefault("used_hints", {})
    used_count = used_map.get(test_type, 0) if test_type is not None else 0
    if used_count >= 10:
        await cb.answer("Лимит подсказок на этот тест исчерпан (10/10)", show_alert=True)
        return

    hint = q.get('hint', '')
    if hint and hint.strip():
        # Увеличиваем счётчик и обновляем число на кнопке
        used_map[test_type] = used_count + 1
        await cb.message.answer(
            _to_html_with_code(f"💡 Подсказка:\n{hint}"),
            parse_mode="HTML",
            reply_markup=get_hint_kb(q_id)
        )
        # Обновим клавиатуру у текущего вопроса, чтобы показать оставшиеся подсказки
        try:
            left = max(0, 10 - used_map[test_type])
            await cb.message.edit_reply_markup(reply_markup=get_stop_test_kb(q_id, hints_left=left))
        except Exception:
            pass
    else:
        await cb.message.answer("Для этого задания нет подсказки.")
    await cb.answer()

# =========================
# 9. Проверка ответа пользователя на вопрос (обычный режим)
# =========================
@router.message(lambda m: (
    m.from_user.id in user_test_state
    and "q_ids" in user_test_state[m.from_user.id]
    and isinstance(getattr(m, "text", None), str)
    and any(ch.isdigit() for ch in m.text)
))
async def check_test_answer(m: types.Message):
    state = user_test_state.get(m.from_user.id)
    idx = state["idx"]
    q_ids = state["q_ids"]
    q = get_question_by_id(q_ids[idx])
    user_answer = ''.join(filter(str.isdigit, m.text))
    correct = ''.join(filter(str.isdigit, str(q.get("correct_answer", ""))))
    is_correct = user_answer == correct
    log_question_answered(m.from_user.id, q["id"], m.text, is_correct)  # --- ЛОГИРОВАНИЕ ОТВЕТА ---

    save_test_answer(
        m.from_user.id,
        getattr(m.from_user, "username", None) or m.from_user.full_name,
        state["type"],
        q["id"],
        q["question"],
        m.text,
        q.get("correct_answer", ""),
        is_correct,
        full_name=get_user_full_name(m.from_user.id)
    )

    # Сообщение с результатом + показываем правильный и ответ ученика
    resp_lines = [
        "✅ Верно!" if is_correct else "❌ Неверно.",
        f"Твой ответ: {user_answer if user_answer else m.text.strip()}",
        f"Правильный ответ: {correct}",
        "",
        f"Вопрос {idx+1} из {len(q_ids)}",
    ]
    resp = "\n".join(resp_lines)
    # Отправляем результат и сохраняем message_id, чтобы позже заменить на краткую строку
    sent = await m.answer(_to_html_with_code(resp), parse_mode="HTML", reply_markup=get_result_kb(q["id"]))
    user_test_state[m.from_user.id]["last_result_msg_id"] = sent.message_id
    # Переход к следующему вопросу только после нажатия «Далее»

# ======================================================================
#       НОВЫЙ ФУНКЦИОНАЛ: РАБОТА НАД ОШИБКАМИ (с кнопками)
# ======================================================================

# --- Кнопка "Работа над ошибками" ---
@router.callback_query(lambda c: c.data == "work_on_mistakes")
async def work_on_mistakes_menu(cb: CallbackQuery):
    user_id = cb.from_user.id
    mistakes = get_mistake_questions(user_id)
    if not mistakes:
        await cb.message.answer("У тебя нет ошибок для исправления! Молодец!")
        await cb.answer()
        return
    mistake_tests = sorted(set(row[0] for row in mistakes))
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"Тест {t}", callback_data=f"mistake_test_{t}")]
            for t in mistake_tests
        ] + [
            [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="to_main_menu")]
        ]
    )
    await cb.message.answer("Выбери тест, где были ошибки:", reply_markup=kb)
    await cb.answer()

# --- Старт работы над ошибками по выбранному тесту ---
@router.callback_query(lambda c: c.data.startswith("mistake_test_"))
async def start_mistake_test(cb: CallbackQuery):
    test_type = int(cb.data.split("_")[-1])
    user_id = cb.from_user.id
    mistakes = [row for row in get_mistake_questions(user_id) if row[0] == test_type]
    if not mistakes:
        await cb.message.answer("Нет ошибок в этом тесте.")
        await cb.answer()
        return
    user_test_state[user_id] = {
        "type": test_type,
        "idx": 0,
        "mistake_q_ids": [row[1] for row in mistakes]
    }
    await send_next_mistake_question(user_id, cb.message)
    await cb.answer()

# --- Отправка следующего ошибочного вопроса ---
async def send_next_mistake_question(user_id, message_obj):
    state = user_test_state.get(user_id)
    idx = state["idx"]
    q_ids = state["mistake_q_ids"]
    if idx >= len(q_ids):
        user_test_state.pop(user_id, None)
        await message_obj.answer("Все ошибки в этом тесте исправлены! 👍")
        return
    q_id = q_ids[idx]
    q = get_question_by_id(q_id)
    log_question_started(user_id, state["type"], q_id)  # --- ЛОГИРОВАНИЕ СТАРТА ---
    options = q['options'].split('\n')
    formatted_q = _format_question_text(q['question'])
    msg = (
        f"Ошибка {idx+1} из {len(q_ids)} (Тест {state['type']})\n\n"
        f"{formatted_q}\n\n" +
        "\n".join([f"{i+1}. {opt}" for i, opt in enumerate(options)]) +
        "\n\nПовтори попытку: введи номер(а) ответа:"
    )
    used_hints = user_test_state.get(user_id, {}).get("used_hints", {}).get(state["type"], 0)
    hints_left = max(0, 10 - used_hints)
    kb = get_stop_test_kb(q_id, hints_left=hints_left)
    sent_q = await message_obj.answer(_to_html_with_code(msg), parse_mode="HTML", reply_markup=kb)
    user_test_state[user_id]["last_question_msg_id"] = sent_q.message_id

# --- Проверка ответа пользователя на ошибочный вопрос ---
@router.message(lambda m: (
    m.from_user.id in user_test_state
    and "mistake_q_ids" in user_test_state[m.from_user.id]
    and isinstance(getattr(m, "text", None), str)
    and any(ch.isdigit() for ch in m.text)
))
async def check_mistake_answer(m: types.Message):
    state = user_test_state.get(m.from_user.id)
    idx = state["idx"]
    q_ids = state["mistake_q_ids"]
    q_id = q_ids[idx]
    q = get_question_by_id(q_id)
    user_answer = ''.join(filter(str.isdigit, m.text))
    correct = ''.join(filter(str.isdigit, str(q.get("correct_answer", ""))))
    is_correct = (user_answer == correct)
    if is_correct:
        set_answer_correct(m.from_user.id, q_id)
        log_question_answered(m.from_user.id, q_id, m.text, True)  # --- ЛОГИРОВАНИЕ ОТВЕТА ---
        user_test_state[m.from_user.id]["idx"] += 1
    else:
        log_question_answered(m.from_user.id, q_id, m.text, False)  # --- ЛОГИРОВАНИЕ ОТВЕТА ---

    resp_lines = [
        "✅ Теперь верно!" if is_correct else "❌ Пока неверно.",
        f"Твой ответ: {user_answer if user_answer else m.text.strip()}",
        f"Правильный ответ: {correct}",
        "",
        f"Ошибка {idx+1} из {len(q_ids)}",
    ]
    resp = "\n".join(resp_lines)
    sent = await m.answer(resp, reply_markup=get_result_kb(q_id))
    user_test_state[m.from_user.id]["last_result_msg_id"] = sent.message_id
    # Переход к следующему вопросу ошибок — только после «Далее»

# =========================
# 10. Кнопка «К заданию» в подсказке — удаляет подсказку
# =========================
@router.callback_query(lambda c: c.data.startswith("back_to_question_"))
async def back_to_question(cb: CallbackQuery):
    try:
        await cb.message.delete()
    except Exception:
        # Если не получилось удалить (нет прав или уже удалено) — просто скрываем кнопки
        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
    await cb.answer()

# --- КОНЕЦ ФАЙЛА ---
