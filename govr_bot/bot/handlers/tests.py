from aiogram import Router, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.filters import Command
import html  # Стандартная библиотека для экранирования HTML

# --- Импортируем все функции работы с базой ---
from bot.services.answer_db import (
    save_test_answer,
    save_test_progress,
    load_test_progress,
    clear_test_progress,
    get_mistake_questions,
    set_answer_correct,
    log_question_started,
    log_question_answered
)
from bot.services.test_sql import get_all_tests_types, get_questions_by_type, get_question_by_id

from bot.handlers.menu import main_kb  # Импорт клавиатуры главного меню

router = Router()
user_test_state = {}

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
def get_stop_test_kb(q_id):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💡 Подсказка", callback_data=f"hint_{q_id}")],
            [InlineKeyboardButton(text="⏹️ Стоп тест", callback_data="stop_test")]
        ]
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
    msg = (
        f"Вопрос {idx+1} из {len(q_ids)} (Тест {state['type']})\n\n"
        f"{q['question']}\n\n" +
        "\n".join([f"{i+1}. {opt}" for i, opt in enumerate(options)]) +
        "\n\nВведите номер(а) ответа (например: 2 или 13):"
    )
    kb = get_stop_test_kb(q['id'])
    await message_obj.answer(msg, reply_markup=kb)

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
    hint = q.get('hint', '')
    if hint and hint.strip():
        await cb.message.answer(html.escape(f"💡 Подсказка:\n{hint}"), parse_mode="HTML")
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
        is_correct
    )

    if is_correct:
        resp = "✅ Верно!"
    else:
        resp = f"❌ Неверно. Правильный ответ: {correct}"
    explanation = q.get("explanation", "") or q.get("detailed_explanation", "")
    if explanation and explanation.strip():
        resp += f"\n\n{explanation}"
    await m.answer(html.escape(resp), parse_mode="HTML")
    user_test_state[m.from_user.id]["idx"] += 1
    await send_next_test_question(m.from_user.id, m)

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
    msg = (
        f"Ошибка {idx+1} из {len(q_ids)} (Тест {state['type']})\n\n"
        f"{q['question']}\n\n" +
        "\n".join([f"{i+1}. {opt}" for i, opt in enumerate(options)]) +
        "\n\nПовтори попытку: введи номер(а) ответа:"
    )
    kb = get_stop_test_kb(q_id)
    await message_obj.answer(msg, reply_markup=kb)

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
    if user_answer == correct:
        resp = "✅ Теперь верно! Ошибка исправлена."
        set_answer_correct(m.from_user.id, q_id)
        log_question_answered(m.from_user.id, q_id, m.text, True)  # --- ЛОГИРОВАНИЕ ОТВЕТА ---
        user_test_state[m.from_user.id]["idx"] += 1
    else:
        resp = f"❌ Пока неверно. Попробуй ещё раз!"
        log_question_answered(m.from_user.id, q_id, m.text, False)  # --- ЛОГИРОВАНИЕ ОТВЕТА ---
    await m.answer(resp)
    await send_next_mistake_question(m.from_user.id, m)

# --- КОНЕЦ ФАЙЛА ---
