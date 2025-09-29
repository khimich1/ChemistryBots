from aiogram import Router, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.filters import Command
from aiogram.exceptions import TelegramBadRequest
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
    get_last_results_for_questions,
    reset_test_results,
)
from bot.services.test_sql import get_all_tests_types, get_questions_by_type, get_question_by_id, mark_question_issue, copy_question_to_tests_bug

from bot.handlers.menu import main_kb  # Импорт клавиатуры главного меню
from bot.services.plan import get_user_plan_code, limits_for, consume_daily
from bot.utils_pkg_new.logger import log_error
from bot.utils_pkg_new.telegram_error_handler import safe_edit_message, handle_telegram_errors
from bot.utils import user_learning_state  # для проверки состояния учебника
from bot.utils_pkg.message_manager import message_manager
import sqlite3

router = Router()
user_test_state = {}

# Для маппинга test_type в групповых заданиях (ЕГЭ как есть, ОГЭ со смещением)
OGE_TYPE_OFFSET = 1000

def _group_test_type(q: dict) -> int:
    t = int(q.get('type') or 0)
    return t if (q.get('exam_type') == 'ege') else (OGE_TYPE_OFFSET + t)

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


def tests_instruction_text() -> str:
    """Красивое и мотивирующее описание раздела тестов."""
    return (
        "🎯 <b>Тренировка и самопроверка</b>\n\n"
        "📚 <b>Что тебя ждёт:</b>\n"
        "• Разнообразные задания по всем темам химии\n"
        "• Мгновенная проверка ответов с объяснениями\n"
        "• Подсказки, если что-то не получается\n"
        "• Работа над ошибками — учись на своих промахах\n"
        "• Прогресс-карта: видишь, что уже знаешь, а что нужно подтянуть\n\n"
        "🚀 <b>Как это работает:</b>\n"
        "1️⃣ Выбери тест по нужной теме\n"
        "2️⃣ Увидишь карту из 30 заданий: ✅ решено верно, ❌ с ошибкой, ⬜ ещё не пробовал\n"
        "3️⃣ Нажимай на номер задания и решай!\n"
        "4️⃣ Получай объяснения и подсказки\n"
        "5️⃣ Отслеживай прогресс и улучшай результат\n\n"
        "💪 <b>Совет:</b> Не бойся ошибок! Каждая ошибка — это шаг к пониманию. "
        "Используй режим «Работа над ошибками» для закрепления материала.\n\n"
        "🎓 <b>Цель:</b> Систематически готовиться к экзамену, выявлять пробелы и превращать их в сильные стороны!"
    )

# =========================
# 1. Клавиатура для выбора тестов
# =========================
def get_tests_types_kb(with_menu: bool = False, include_back: bool = False, user_id: int = None):
    
    types = get_all_tests_types()
    
    # Создаем кнопки в 3 столбика
    keyboard = []
    for i in range(0, len(types), 3):
        row = []
        # Первая кнопка в ряду
        if i < len(types) and types[i] not in (None, ''):
            row.append(InlineKeyboardButton(text=f"Тест {types[i]}", callback_data=f"choose_test_{types[i]}"))
        # Вторая кнопка в ряду (если есть)
        if i + 1 < len(types) and types[i + 1] not in (None, ''):
            row.append(InlineKeyboardButton(text=f"Тест {types[i + 1]}", callback_data=f"choose_test_{types[i + 1]}"))
        # Третья кнопка в ряду (если есть)
        if i + 2 < len(types) and types[i + 2] not in (None, ''):
            row.append(InlineKeyboardButton(text=f"Тест {types[i + 2]}", callback_data=f"choose_test_{types[i + 2]}"))
        if row:  # Добавляем ряд только если в нем есть кнопки
            keyboard.append(row)
    
    # --- Кнопка "Работа над ошибками"
    keyboard.append([InlineKeyboardButton(text="💡 Работа над ошибками", callback_data="work_on_mistakes")])
    if include_back:
        keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="tests_go_back")])
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

def get_test_grid_kb(user_id: int, test_type: int, q_ids: list[int]) -> InlineKeyboardMarkup:
    """
    30 кнопок как 3 столбца × 10 строк. Обозначения в подписи:
      N✓ — последний ответ верный, N✗ — неверный, N· — не решался.
    """
    status = get_last_results_for_questions(user_id, test_type, q_ids)
    def _label(i0: int) -> tuple[str, str]:
        num = i0 + 1
        st = status.get(q_ids[i0])
        mark = "✅" if st == 1 else "❌" if st == 0 else "⬜"
        return f"{num}{mark}", f"jump_{test_type}_{num}"

    # Три столбца по 10 строк: i, i+10, i+20
    rows: list[list[InlineKeyboardButton]] = []
    limit = min(30, len(q_ids))
    for r in range(10):
        row: list[InlineKeyboardButton] = []
        for c in range(3):
            idx = r + 10 * c
            if idx < limit:
                text, cb = _label(idx)
                row.append(InlineKeyboardButton(text=text, callback_data=cb))
        if row:
            rows.append(row)
    rows.append([
        InlineKeyboardButton(text="🔄 Начать заново", callback_data=f"restart_test_{test_type}"),
        InlineKeyboardButton(text="📊 Статистика", callback_data=f"show_stats_{test_type}"),
    ])
    rows.append([
        InlineKeyboardButton(text="🧹 Скрыть таблицу", callback_data="hide_grid"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def generate_test_stats(user_id: int, test_type: int, q_ids: list[int]) -> str:
    """Генерирует статистику прохождения теста."""
    status = get_last_results_for_questions(user_id, test_type, q_ids)
    
    total = len(q_ids)
    correct = sum(1 for st in status.values() if st == 1)
    incorrect = sum(1 for st in status.values() if st == 0)
    not_attempted = total - correct - incorrect
    
    if total == 0:
        return "📊 <b>Статистика теста {test_type}</b>\n\nНет данных для анализа."
    
    percentage = (correct / total) * 100 if total > 0 else 0
    
    # Определяем уровень
    if percentage >= 90:
        level = "🟢 Отлично"
    elif percentage >= 75:
        level = "🟡 Хорошо"
    elif percentage >= 60:
        level = "🟠 Удовлетворительно"
    else:
        level = "🔴 Требует доработки"
    
    stats_text = (
        f"📊 <b>Статистика теста {test_type}</b>\n\n"
        f"🎯 <b>Общий прогресс:</b> {level}\n"
        f"📈 <b>Процент правильных ответов:</b> {percentage:.1f}%\n\n"
        f"📋 <b>Детализация:</b>\n"
        f"✅ Правильно: {correct} из {total} ({correct/total*100:.1f}%)\n"
        f"❌ Неправильно: {incorrect} из {total} ({incorrect/total*100:.1f}%)\n"
        f"⬜ Не решал: {not_attempted} из {total} ({not_attempted/total*100:.1f}%)\n\n"
    )
    
    # Добавляем мотивацию
    if correct == total:
        stats_text += "🎉 <b>Поздравляем! Ты отлично справился с тестом!</b>"
    elif correct > incorrect:
        stats_text += "💪 <b>Хорошая работа! Продолжай в том же духе!</b>"
    elif correct == 0 and incorrect > 0:
        stats_text += "💡 <b>Не расстраивайся! Каждая ошибка — это шаг к пониманию. Попробуй ещё раз!</b>"
    else:
        stats_text += "📚 <b>Есть над чем поработать! Используй режим «Работа над ошибками».</b>"
    
    return stats_text

def get_stats_kb(test_type: int) -> InlineKeyboardMarkup:
    """Клавиатура для статистики с кнопкой возврата к таблице."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📋 К таблице", callback_data=f"back_to_grid_{test_type}")],
            [InlineKeyboardButton(text="⬅️ В главное меню", callback_data="to_main_menu")],
        ]
    )

# =========================
# 3. Показываем меню тестов
# =========================
@router.message(lambda m: m.text == "📝 Тесты")
async def show_tests_types_menu(m: types.Message):
    # Удаляем только сохранённые сообщения - этого достаточно
    await message_manager.delete_user_messages(m.bot, m.from_user.id, m.chat.id)
    
    msg1 = await m.answer(tests_instruction_text(), parse_mode="HTML")
    message_manager.add_message(m.from_user.id, msg1.message_id)
    msg2 = await m.answer("Выбери номер теста:", reply_markup=get_tests_types_kb(with_menu=True, include_back=True, user_id=m.from_user.id))
    message_manager.add_message(m.from_user.id, msg2.message_id)

@router.message(Command("tests"))
async def show_tests_menu_cmd(m: types.Message):
    await show_tests_types_menu(m)

# =========================
# 4. Начать тест (по callback-кнопке) с проверкой прогресса
# =========================
@router.callback_query(lambda c: c.data.startswith("choose_test_"))
async def start_test(cb: CallbackQuery):
    # Удаляем только сохранённые сообщения - этого достаточно
    await message_manager.delete_user_messages(cb.message.bot, cb.from_user.id, cb.message.chat.id)
    
    try:
        test_type = int(cb.data.split("_")[-1])
    except ValueError:
        await cb.answer("Ошибка: неверный номер теста.")
        return

    # Удалим предыдущую сетку, если была (при переключении тестов)
    try:
        prev = user_test_state.get(cb.from_user.id) or {}
        prev_grid_id = prev.get("grid_msg_id")
        if prev_grid_id:
            await cb.message.bot.delete_message(chat_id=cb.message.chat.id, message_id=prev_grid_id)
    except (ValueError, TypeError) as e:
        log_error(e, f"Data error deleting previous grid message for user {cb.from_user.id}", user_id=cb.from_user.id)
    except (AttributeError, KeyError) as e:
        log_error(e, f"Unexpected error deleting previous grid message for user {cb.from_user.id}", user_id=cb.from_user.id)
    except TelegramBadRequest as e:
        # Сообщение уже удалено или не существует - это нормально
        log_error(e, f"Message to delete not found for user {cb.from_user.id}", user_id=cb.from_user.id)

    idx, q_ids = load_test_progress(cb.from_user.id, test_type)
    if idx is not None and q_ids:
        kb = get_test_grid_kb(cb.from_user.id, test_type, q_ids)
        sent = await cb.message.answer(f"Тест {test_type}. Выбери номер задания или нажми «Начать заново»:", reply_markup=kb)
        message_manager.add_message(cb.from_user.id, sent.message_id)
        # Сохраним id сообщения-сетки и прогресс, чтобы потом обновлять цвета
        st = user_test_state.setdefault(cb.from_user.id, {})
        st.update({
            "type": test_type,
            "idx": idx,
            "q_ids": q_ids,
            "grid_msg_id": sent.message_id,
            "answered": False,  # Сбрасываем флаг answered при начале теста
        })
        await cb.answer()
        return

    # --- Если прогресса нет — стандартное поведение ---
    questions = get_questions_by_type(test_type)
    if not questions:
        sent_none = await cb.message.answer("Нет вопросов для этого теста.")
        message_manager.add_message(cb.from_user.id, sent_none.message_id)
        await cb.answer()
        return
    user_test_state[cb.from_user.id] = {
        "type": test_type,
        "idx": 0,
        "q_ids": [q["id"] for q in questions],
        "answered": False,  # Сбрасываем флаг answered при начале теста
    }
    clear_test_progress(cb.from_user.id, test_type)
    # Показать сетку перед началом и сохранить её id
    grid_kb = get_test_grid_kb(cb.from_user.id, test_type, user_test_state[cb.from_user.id]["q_ids"])
    sent_grid = await cb.message.answer(f"Тест {test_type}. Выбери номер задания или нажми «Начать заново»:", reply_markup=grid_kb)
    user_test_state[cb.from_user.id]["grid_msg_id"] = sent_grid.message_id
    message_manager.add_message(cb.from_user.id, sent_grid.message_id)
    await cb.answer()

@router.callback_query(lambda c: c.data.startswith("explain_"))
async def show_explanation(cb: CallbackQuery):
    # --- Лимит объяснений в день по тарифу ---
    user_id = cb.from_user.id
    plan = get_user_plan_code(user_id)
    limit = limits_for(plan)["test_explain_per_day"]
    ok, _left = consume_daily(user_id, "test_explain", limit)
    if not ok:
        try:
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💳 Тарифы и оплата", callback_data="to_tariffs")]])
            await cb.message.answer("Дневной лимит объяснений исчерпан. Оформи подписку для безлимита.", reply_markup=kb)
        except (ValueError, TypeError) as e:
            log_error(e, f"Data error sending tariff message for user {cb.from_user.id}", user_id=cb.from_user.id)
        except (AttributeError, KeyError) as e:
            log_error(e, f"Unexpected error sending tariff message for user {cb.from_user.id}", user_id=cb.from_user.id)
        await cb.answer()
        return
    q_id = int(cb.data.split("_")[-1])
    q = get_question_by_id(q_id)
    explanation = q.get("explanation", "") or q.get("detailed_explanation", "")
    if explanation and explanation.strip():
        sent = await cb.message.answer(
            _to_html_with_code(f"🧠 Объяснение:\n{explanation}"),
            parse_mode="HTML",
            reply_markup=get_next_kb(q_id)
        )
        message_manager.add_message(cb.from_user.id, sent.message_id)
    else:
        sent = await cb.message.answer("Пока нет объяснения к этому заданию.")
        message_manager.add_message(cb.from_user.id, sent.message_id)
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
            except (ValueError, TypeError) as e:
                log_error(e, f"Data error deleting explanation message for user {cb.from_user.id}", user_id=cb.from_user.id)
                # если не удалилось — хотя бы скрыть клавиатуру
                try:
                    await cb.message.edit_reply_markup(reply_markup=None)
                except (ValueError, TypeError) as e2:
                    log_error(e2, f"Data error hiding keyboard for user {cb.from_user.id}", user_id=cb.from_user.id)
                except Exception as e2:
                    log_error(e2, f"Unexpected error hiding keyboard for user {cb.from_user.id}", user_id=cb.from_user.id)
            except Exception as e:
                log_error(e, f"Unexpected error deleting explanation message for user {cb.from_user.id}", user_id=cb.from_user.id)
                # если не удалилось — хотя бы скрыть клавиатуру
                try:
                    await cb.message.edit_reply_markup(reply_markup=None)
                except (ValueError, TypeError) as e2:
                    log_error(e2, f"Data error hiding keyboard for user {cb.from_user.id}", user_id=cb.from_user.id)
                except Exception as e2:
                    log_error(e2, f"Unexpected error hiding keyboard for user {cb.from_user.id}", user_id=cb.from_user.id)
        else:
            if q_id:
                try:
                    await cb.message.edit_reply_markup(reply_markup=get_explain_only_kb(q_id))
                except (ValueError, TypeError) as e:
                    log_error(e, f"Data error editing reply markup for user {cb.from_user.id}", user_id=cb.from_user.id)
                except Exception as e:
                    log_error(e, f"Unexpected error editing reply markup for user {cb.from_user.id}", user_id=cb.from_user.id)
    except (ValueError, TypeError) as e:
        log_error(e, f"Data error in go_next_question for user {cb.from_user.id}", user_id=cb.from_user.id)
    except (AttributeError, KeyError) as e:
        log_error(e, f"Unexpected error in go_next_question for user {cb.from_user.id}", user_id=cb.from_user.id)
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
        except (ValueError, TypeError) as e:
            log_error(e, f"Data error deleting last question message for user {cb.from_user.id}", user_id=cb.from_user.id)
        except (AttributeError, KeyError) as e:
            log_error(e, f"Unexpected error deleting last question message for user {cb.from_user.id}", user_id=cb.from_user.id)
        st["idx"] += 1
        # Сбрасываем флаг answered для нового вопроса
        st["answered"] = False
        await send_next_test_question(cb.from_user.id, cb.message, is_callback=True)
        await cb.answer()
        return

    # Если это режим ошибок
    if "mistake_q_ids" in st:
        try:
            last_q_id = st.pop("last_question_msg_id", None)
            if last_q_id:
                await cb.message.bot.delete_message(chat_id=cb.message.chat.id, message_id=last_q_id)
        except (ValueError, TypeError) as e:
            log_error(e, f"Data error deleting last mistake question message for user {cb.from_user.id}", user_id=cb.from_user.id)
        except (AttributeError, KeyError) as e:
            log_error(e, f"Unexpected error deleting last mistake question message for user {cb.from_user.id}", user_id=cb.from_user.id)
        st["idx"] += 1
        # Сбрасываем флаг answered для нового вопроса
        st["answered"] = False
        await send_next_mistake_question(cb.from_user.id, cb.message)
        await cb.answer()
        return

    await cb.answer()

@router.callback_query(lambda c: c.data.startswith("jump_"))
async def jump_to_question(cb: CallbackQuery):
    # Формат: jump_{test_type}_{number}
    parts = cb.data.split("_")
    if len(parts) != 3:
        await cb.answer()
        return
    test_type = int(parts[1])
    number = max(1, int(parts[2]))
    _idx, q_ids = load_test_progress(cb.from_user.id, test_type)
    if not q_ids:
        questions = get_questions_by_type(test_type)
        if not questions:
            sent = await cb.message.answer("Нет вопросов для этого теста.")
            message_manager.add_message(cb.from_user.id, sent.message_id)
            await cb.answer()
            return
        q_ids = [q["id"] for q in questions]
    number = min(number, len(q_ids))
    # Удаляем предыдущее сообщение-вопрос, если было
    try:
        st_prev = user_test_state.get(cb.from_user.id) or {}
        last_q_msg_id = st_prev.pop("last_question_msg_id", None)
        if last_q_msg_id:
            await cb.message.bot.delete_message(chat_id=cb.message.chat.id, message_id=last_q_msg_id)
    except (ValueError, TypeError) as e:
        log_error(e, f"Data error deleting previous question message in jump_to_question for user {cb.from_user.id}", user_id=cb.from_user.id)
    except (AttributeError, KeyError) as e:
        log_error(e, f"Unexpected error deleting previous question message in jump_to_question for user {cb.from_user.id}", user_id=cb.from_user.id)
    except TelegramBadRequest as e:
        # Сообщение уже удалено или не существует - это нормально
        log_error(e, f"Message to delete not found in jump_to_question for user {cb.from_user.id}", user_id=cb.from_user.id)

    prev = user_test_state.get(cb.from_user.id) or {}
    user_test_state[cb.from_user.id] = {
        "type": test_type,
        "idx": number - 1,
        "q_ids": q_ids,
        "grid_msg_id": prev.get("grid_msg_id"),
        "used_hints": prev.get("used_hints", {}),
        "answered": False,  # Сбрасываем флаг answered при переходе к вопросу
    }
    await send_next_test_question(cb.from_user.id, cb.message, is_callback=True)
    await cb.answer()

# =========================
# 5.1 Жалоба на вопрос
# =========================
@router.callback_query(lambda c: c.data and c.data.startswith("report_") and c.data[7:].isdigit())
async def report_question(cb: CallbackQuery):
    q_id = int(cb.data.split("_")[-1])
    # Пытаемся удалить сообщение-вопрос сразу при нажатии «Пожаловаться»
    try:
        st = user_test_state.get(cb.from_user.id) or {}
        last_q_id = st.pop("last_question_msg_id", None)
        if last_q_id:
            await cb.message.bot.delete_message(chat_id=cb.message.chat.id, message_id=last_q_id)
    except (ValueError, TypeError) as e:
        log_error(e, f"Data error deleting question message in report_question for user {cb.from_user.id}", user_id=cb.from_user.id)
    except (AttributeError, KeyError) as e:
        log_error(e, f"Unexpected error deleting question message in report_question for user {cb.from_user.id}", user_id=cb.from_user.id)
    except TelegramBadRequest as e:
        # Сообщение уже удалено или не существует - это нормально
        log_error(e, f"Message to delete not found in report_question for user {cb.from_user.id}", user_id=cb.from_user.id)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📝 Проблема с заданием", callback_data=f"report_reason_{q_id}_task")],
            [InlineKeyboardButton(text="💡 Проблема с подсказкой", callback_data=f"report_reason_{q_id}_hint")],
            [InlineKeyboardButton(text="✅ Проблема с ответом", callback_data=f"report_reason_{q_id}_answer")],
            [InlineKeyboardButton(text="✍️ Свой вариант", callback_data=f"report_reason_{q_id}_custom")],
        ]
    )
    sent = await cb.message.answer("Что именно смутило в этом задании?", reply_markup=kb)
    message_manager.add_message(cb.from_user.id, sent.message_id)
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
    # Сохраняем текущую версию вопроса в tests_bug для правки в препод-боте
    copy_question_to_tests_bug(q_id)
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
        except ValueError as e:
            log_error(e, f"ValueError removing q_id {q_id} from mistake_q_ids for user {cb.from_user.id}", user_id=cb.from_user.id)
        except (AttributeError, KeyError) as e:
            log_error(e, f"Unexpected error removing q_id {q_id} from mistake_q_ids for user {cb.from_user.id}", user_id=cb.from_user.id)
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
        copy_question_to_tests_bug(q_id)
        save_test_debug(q_id, reason or "", status="не решено")
        await m.answer("Спасибо за подробности! Вопрос скрыт до исправления.")
    else:
        await m.answer("Спасибо! Записал жалобу.")

    # Продолжаем тест
    if "mistake_q_ids" in st and q_id is not None:
        try:
            st["mistake_q_ids"].remove(q_id)
        except ValueError as e:
            log_error(e, f"ValueError removing q_id {q_id} from mistake_q_ids in report_custom_text for user {m.from_user.id}", user_id=m.from_user.id)
        except (AttributeError, KeyError) as e:
            log_error(e, f"Unexpected error removing q_id {q_id} from mistake_q_ids in report_custom_text for user {m.from_user.id}", user_id=m.from_user.id)
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
    # Сброс прогресса и результатов (не отправляем сразу вопрос)
    clear_test_progress(cb.from_user.id, test_type)
    reset_test_results(cb.from_user.id, test_type)
    # Сброс локального счётчика подсказок
    used_map = user_test_state.setdefault(cb.from_user.id, {}).setdefault("used_hints", {})
    try:
        used_map.pop(test_type, None)
    except (ValueError, TypeError) as e:
        log_error(e, f"Data error popping test_type {test_type} from used_hints for user {cb.from_user.id}", user_id=cb.from_user.id)
    except (AttributeError, KeyError) as e:
        log_error(e, f"Unexpected error popping test_type {test_type} from used_hints for user {cb.from_user.id}", user_id=cb.from_user.id)
    prev = user_test_state.get(cb.from_user.id) or {}
    user_test_state[cb.from_user.id] = {
        "type": test_type,
        "idx": 0,
        "q_ids": [q["id"] for q in questions],
        "grid_msg_id": prev.get("grid_msg_id"),
        "used_hints": prev.get("used_hints", {}),
    }
    # Перерисуем таблицу со сброшенными статусами
    try:
        grid_id = user_test_state[cb.from_user.id].get("grid_msg_id")
        kb = get_test_grid_kb(cb.from_user.id, test_type, user_test_state[cb.from_user.id]["q_ids"])
        if grid_id:
            # Безопасное редактирование с обработкой "message is not modified"
            try:
                await cb.message.bot.edit_message_reply_markup(
                    chat_id=cb.message.chat.id, 
                    message_id=grid_id, 
                    reply_markup=kb
                )
            except TelegramBadRequest as e:
                # Игнорируем "message is not modified", остальное логируем
                if "message is not modified" not in str(e).lower():
                    log_error(e, f"Error updating grid markup for user {cb.from_user.id}", user_id=cb.from_user.id)
            except (AttributeError, KeyError) as e:
                log_error(e, f"Error updating grid markup for user {cb.from_user.id}", user_id=cb.from_user.id)
        else:
            sent = await cb.message.answer(f"Тест {test_type}. Выбери номер задания или нажми «Начать заново»:", reply_markup=kb)
            user_test_state[cb.from_user.id]["grid_msg_id"] = sent.message_id
    except (ValueError, TypeError) as e:
        log_error(e, f"Data error redrawing test grid for user {cb.from_user.id}", user_id=cb.from_user.id)
    except (AttributeError, KeyError) as e:
        log_error(e, f"Unexpected error redrawing test grid for user {cb.from_user.id}", user_id=cb.from_user.id)
    await cb.answer()

# =========================
# 5. Отправить следующий вопрос теста
# =========================
async def send_next_test_question(user_id, message_obj, is_callback=False):
    state = user_test_state.get(user_id)
    if not state:
        return
    # Перед показом нового вопроса удалим только сообщения с результатами ответов
    # НЕ удаляем grid сообщение, так как оно может понадобиться для редактирования
    try:
        # Удаляем только сообщения с результатами, но сохраняем grid
        last_result_msg_id = state.get("last_result_msg_id")
        if last_result_msg_id:
            try:
                await message_obj.bot.delete_message(chat_id=message_obj.chat.id, message_id=last_result_msg_id)
            except Exception:
                pass
        last_question_msg_id = state.get("last_question_msg_id") 
        if last_question_msg_id:
            try:
                await message_obj.bot.delete_message(chat_id=message_obj.chat.id, message_id=last_question_msg_id)
            except Exception:
                pass
    except Exception:
        pass
    idx = state["idx"]
    q_ids = state["q_ids"]
    if idx >= len(q_ids):
        user_test_state.pop(user_id, None)
        sent_end = await message_obj.answer("Тест завершён! Возвращаюсь в меню.")
        message_manager.add_message(user_id, sent_end.message_id)
        return
    
    # Используем новую функцию для получения вопроса с изображением
    from bot.services.test_sql import get_question_with_image
    q = get_question_with_image(q_ids[idx])
    
    if not q:
        await message_obj.answer("Ошибка: вопрос не найден.")
        return
        
    log_question_started(user_id, state["type"], q["id"])  # --- ЛОГИРОВАНИЕ СТАРТА ---
    
    # Формируем текст вопроса
    formatted_q = _format_question_text(q['question'])
    msg = (
        f"Вопрос {idx+1} из {len(q_ids)} (Тест {state['type']})\n\n"
        f"{formatted_q}\n\n"
    )
    
    # Добавляем варианты ответов, если они есть
    if q['options']:
        options = q['options'].split('\n')
        msg += "\n".join([f"{i+1}. {opt}" for i, opt in enumerate(options)]) + "\n\n"
    
    msg += "Введите номер(а) ответа (например: 2 или 13):"
    
    # Подсказки: максимум 10 на 30 вопросов одного теста
    # Считаем, сколько подсказок уже использовано в текущем тесте
    used_hints = user_test_state.get(user_id, {}).get("used_hints", {}).get(state["type"], 0)
    hints_left = max(0, 10 - used_hints)
    kb = get_stop_test_kb(q['id'], hints_left=hints_left)
    
    # Отправляем сообщение с изображением(ями), если есть
    if q.get('image') or q.get('images'):
        try:
            from aiogram.types import BufferedInputFile
            
            # Если одно изображение (старый формат)
            if q.get('image'):
                image_bytes = q['image']['data']
                photo_file = BufferedInputFile(
                    file=image_bytes,
                    filename=q['image'].get('filename', 'question.png')
                )
                
                sent_q = await message_obj.answer_photo(
                    photo=photo_file,
                    caption=_to_html_with_code(msg),
                    parse_mode="HTML",
                    reply_markup=kb
                )
            
            # Если несколько изображений (новый формат)
            elif q.get('images'):
                # Создаём список BufferedInputFile для всех изображений
                photo_files = []
                for img in q['images']:
                    photo_file = BufferedInputFile(
                        file=img['data'],
                        filename=img.get('filename', 'question.png')
                    )
                    photo_files.append(photo_file)
                
                # Отправляем медиа-группу с несколькими изображениями
                from aiogram.types import InputMediaPhoto
                media_group = []
                
                # Первое изображение с подписью
                media_group.append(InputMediaPhoto(
                    media=photo_files[0],
                    caption=_to_html_with_code(msg),
                    parse_mode="HTML"
                ))
                
                # Остальные изображения без подписи
                for photo_file in photo_files[1:]:
                    media_group.append(InputMediaPhoto(media=photo_file))
                
                # Отправляем медиа-группу
                sent_messages = await message_obj.answer_media_group(media_group)
                sent_q = sent_messages[0]  # Берём первое сообщение для сохранения ID
                
                # Отправляем клавиатуру отдельным сообщением
                sent_kb = await message_obj.answer("Выберите действие:", reply_markup=kb)
                message_manager.add_message(user_id, sent_kb.message_id)
                
        except Exception as e:
            # Если не удалось отправить изображение, отправляем обычное сообщение
            from bot.utils_pkg_new.logger import log_error
            log_error(e, f"Failed to send image(s) for question {q['id']}", user_id=user_id)
            sent_q = await message_obj.answer(_to_html_with_code(msg), parse_mode="HTML", reply_markup=kb)
    else:
        # Отправляем обычное сообщение без изображения
        sent_q = await message_obj.answer(_to_html_with_code(msg), parse_mode="HTML", reply_markup=kb)
    
    # Запомним id сообщения-вопроса, чтобы удалить его при переходе «Далее»
    user_test_state[user_id]["last_question_msg_id"] = sent_q.message_id
    message_manager.add_message(user_id, sent_q.message_id)

# =========================
# 6. Обработчик: Стоп тест (универсально для обоих режимов)
# =========================
@router.callback_query(lambda c: c.data == "stop_test")
async def stop_test(cb: CallbackQuery):
    state = user_test_state.pop(cb.from_user.id, None)
    
    # Очищаем состояние карточек при остановке теста
    try:
        from bot.handlers.flashcards import user_flashcards_state
        user_id = cb.from_user.id
        if user_id in user_flashcards_state:
            user_flashcards_state[user_id] = {}
    except (ImportError, ModuleNotFoundError) as e:
        log_error(e, f"Import error clearing flashcards state for user {cb.from_user.id}", user_id=cb.from_user.id)
        pass
    
    # --- Если работаем над ошибками ---
    if state and "mistake_q_ids" in state:
        await cb.message.answer(
            "Разбор ошибок завершён! Возвращаюсь в раздел тестов.",
            reply_markup=get_tests_types_kb(with_menu=True, user_id=cb.from_user.id)
        )
    elif state:
        save_test_progress(cb.from_user.id, state["type"], state["idx"], state["q_ids"])
        await cb.message.answer(
            "Тест прерван! Выбери тест для прохождения:",
            reply_markup=get_tests_types_kb(with_menu=True, user_id=cb.from_user.id)
        )
    else:
        await cb.message.answer(
            "Действие отменено. Выбери тест:",
            reply_markup=get_tests_types_kb(with_menu=True, user_id=cb.from_user.id)
        )
    await cb.answer()

# =========================
# 6.1 Скрыть таблицу с номерами
# =========================
@router.callback_query(lambda c: c.data == "hide_grid")
async def hide_grid(cb: CallbackQuery):
    try:
        st = user_test_state.get(cb.from_user.id) or {}
        grid_id = st.pop("grid_msg_id", None)
        if grid_id:
            await cb.message.bot.delete_message(chat_id=cb.message.chat.id, message_id=grid_id)
            user_test_state[cb.from_user.id] = st
    except (ValueError, TypeError) as e:
        log_error(e, f"Data error hiding grid for user {cb.from_user.id}", user_id=cb.from_user.id)
    except TelegramBadRequest as e:
        # Сообщение уже удалено или не существует - это нормально
        log_error(e, f"Message to delete not found in hide_grid for user {cb.from_user.id}", user_id=cb.from_user.id)
    except (AttributeError, KeyError) as e:
        log_error(e, f"Unexpected error hiding grid for user {cb.from_user.id}", user_id=cb.from_user.id)
    await cb.answer()

# =========================
# 6.2 Показать статистику теста
# =========================
@router.callback_query(lambda c: c.data.startswith("show_stats_"))
async def show_test_stats(cb: CallbackQuery):
    try:
        test_type = int(cb.data.split("_")[-1])
    except ValueError:
        await cb.answer("Ошибка: неверный номер теста.")
        return
    
    # Получаем список вопросов для теста
    questions = get_questions_by_type(test_type)
    if not questions:
        await cb.message.answer("Нет вопросов для этого теста.")
        await cb.answer()
        return
    
    q_ids = [q["id"] for q in questions]
    
    # Генерируем статистику
    stats_text = generate_test_stats(cb.from_user.id, test_type, q_ids)
    stats_kb = get_stats_kb(test_type)
    
    # Сохраняем ID сообщения со статистикой для возможности удаления
    sent = await cb.message.answer(stats_text, parse_mode="HTML", reply_markup=stats_kb)
    
    # Сохраняем ID сообщения со статистикой в состоянии пользователя
    st = user_test_state.setdefault(cb.from_user.id, {})
    st["stats_msg_id"] = sent.message_id
    user_test_state[cb.from_user.id] = st
    
    await cb.answer()

# =========================
# 6.3 Вернуться к таблице из статистики
# =========================
@router.callback_query(lambda c: c.data.startswith("back_to_grid_"))
async def back_to_grid(cb: CallbackQuery):
    try:
        test_type = int(cb.data.split("_")[-1])
    except ValueError:
        await cb.answer("Ошибка: неверный номер теста.")
        return
    
    # Удаляем сообщение со статистикой
    try:
        st = user_test_state.get(cb.from_user.id) or {}
        stats_msg_id = st.pop("stats_msg_id", None)
        if stats_msg_id:
            await cb.message.bot.delete_message(chat_id=cb.message.chat.id, message_id=stats_msg_id)
            user_test_state[cb.from_user.id] = st
    except (ValueError, TypeError) as e:
        log_error(e, f"Data error deleting stats message for user {cb.from_user.id}", user_id=cb.from_user.id)
    except TelegramBadRequest as e:
        # Сообщение уже удалено или не существует - это нормально
        log_error(e, f"Message to delete not found in back_to_grid for user {cb.from_user.id}", user_id=cb.from_user.id)
    except (AttributeError, KeyError) as e:
        log_error(e, f"Unexpected error deleting stats message for user {cb.from_user.id}", user_id=cb.from_user.id)
    
    # Получаем список вопросов для теста
    questions = get_questions_by_type(test_type)
    if not questions:
        await cb.message.answer("Нет вопросов для этого теста.")
        await cb.answer()
        return
    
    q_ids = [q["id"] for q in questions]
    
    # Показываем таблицу снова
    grid_kb = get_test_grid_kb(cb.from_user.id, test_type, q_ids)
    sent = await cb.message.answer(f"Тест {test_type}. Выбери номер задания или нажми «Начать заново»:", reply_markup=grid_kb)
    
    # Сохраняем ID сообщения-сетки
    st = user_test_state.setdefault(cb.from_user.id, {})
    st["grid_msg_id"] = sent.message_id
    user_test_state[cb.from_user.id] = st
    
    await cb.answer()

# =========================
# 7. Обработчик кнопки возврата в главное меню
# =========================
@router.callback_query(lambda c: c.data == "group_assignments")
async def show_group_assignments(cb: CallbackQuery):
    """Показывает задания для группы студента"""
    from bot.services.teacher_access import get_group_tasks_for_user, get_user_group_number
    
    await cb.answer()
    
    user_id = cb.from_user.id
    group_no = get_user_group_number(user_id)
    
    if not group_no:
        await cb.message.answer("❌ Вы не состоите в группе или произошла ошибка.")
        return
    
    tasks = get_group_tasks_for_user(user_id)
    
    if not tasks:
        await cb.message.answer(f"📂 <b>Задания для группы {group_no}</b>\n\nПока нет заданий от преподавателя.", parse_mode="HTML")
        return
    
    # Формируем список заданий
    tasks_text = f"📂 <b>Задания для группы {group_no}</b>\n\n"
    keyboard = []
    
    for task in tasks:
        tasks_text += f"📋 {task['title']}\n"
        tasks_text += f"📅 Создано: {task['created_at']}\n\n"
        
        # Добавляем кнопку для запуска задания
        keyboard.append([
            InlineKeyboardButton(
                text=f"▶️ {task['title']}", 
                callback_data=f"start_group_task_{task['id']}"
            )
        ])
    
    # Добавляем кнопку "Назад"
    keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="tests_go_back")])
    
    await cb.message.answer(
        tasks_text, 
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )


@router.callback_query(lambda c: c.data.startswith("start_group_task_"))
async def start_group_task(cb: CallbackQuery):
    """Запускает задание группы"""
    from bot.services.teacher_access import get_group_tasks_for_user, get_user_group_number
    import sqlite3
    import os
    
    await cb.answer()
    
    try:
        task_id = int(cb.data.split("_")[-1])
    except ValueError:
        await cb.message.answer("❌ Ошибка: неверный ID задания.")
        return
    
    user_id = cb.from_user.id
    tasks = get_group_tasks_for_user(user_id)
    
    # Находим нужное задание
    task = None
    for t in tasks:
        if t['id'] == task_id:
            task = t
            break
    
    if not task:
        await cb.message.answer("❌ Задание не найдено.")
        return
    
    # Парсим items (формат: "ege:1, ege:5, oge:3")
    items = task['items']
    question_ids = []
    
    for item in items.split(','):
        item = item.strip()
        if ':' in item:
            exam_type, q_id = item.split(':', 1)
            exam_type = exam_type.strip().lower()
            q_id = q_id.strip()
            
            if q_id.isdigit():
                question_ids.append((exam_type, int(q_id)))
    
    if not question_ids:
        await cb.message.answer("❌ В задании нет вопросов.")
        return
    
    # Получаем вопросы из соответствующих сервисов с поддержкой изображений
    questions = []
    
    for exam_type, q_id in question_ids:
        try:
            if exam_type == 'ege':
                from bot.services.test_sql import get_question_with_image as get_ege_question
                q = get_ege_question(int(q_id))
            elif exam_type == 'oge':
                from bot.services.test_sql_oge import get_question_with_image as get_oge_question
                q = get_oge_question(int(q_id))
            else:
                q = None
            
            if q:
                questions.append({
                    'id': q.get('id'),
                    'type': q.get('type'),
                    'question': q.get('question', ''),
                    'options': q.get('options', ''),
                    'correct_answer': q.get('correct_answer', ''),
                    'explanation': q.get('explanation', ''),
                    'hint': q.get('hint', ''),
                    'exam_type': exam_type,
                    'image': q.get('image'),
                    'images': q.get('images')
                })
        except Exception as e:
            from bot.utils_pkg_new.logger import log_error
            log_error(e, f"Failed to load question {q_id} for exam_type {exam_type}", user_id=user_id)
    
    if not questions:
        await cb.message.answer("❌ Не удалось загрузить вопросы.")
        return
    
    # Сохраняем состояние теста группы
    if user_id not in user_test_state:
        user_test_state[user_id] = {}
    
    user_test_state[user_id].update({
        'is_group_task': True,
        'group_task_id': task_id,
        'group_task_title': task['title'],
        'questions': questions,
        'current_question': 0,
        'correct_answers': 0,
        'total_questions': len(questions),
        'start_time': None,
        'grid_msg_id': None
    })
    
    # Запускаем первый вопрос
    await start_group_question(cb, user_id)


async def start_group_question(cb: CallbackQuery, user_id: int):
    """Показывает вопрос группового задания"""
    state = user_test_state.get(user_id, {})
    questions = state.get('questions', [])
    current_question = state.get('current_question', 0)
    
    if current_question >= len(questions):
        # Тест завершен
        await finish_group_test(cb, user_id)
        return
    
    question = questions[current_question]
    
    # Логируем старт вопроса группового задания
    try:
        log_question_started(user_id, _group_test_type(question), question['id'])
    except Exception:
        pass
    
    # Формируем текст вопроса
    question_text = f"📋 <b>Задание группы: {state.get('group_task_title', '')}</b>\n\n"
    question_text += f"❓ <b>Вопрос {current_question + 1} из {len(questions)}</b>\n\n"
    question_text += f"{question['question']}\n\n"
    
    # Добавляем варианты ответов
    options = question.get('options', '')
    if options:
        question_text += f"{options}\n\n"
    
    # Для OGE вопросов ученик должен вводить ответы числами
    # Показываем инструкцию вместо кнопок
    question_text += "\n\n💡 <b>Введите номера выбранных вариантов в одном сообщении (например: 13 или 24)</b>"
    
    keyboard = []
    
    # Кнопки управления
    keyboard.append([InlineKeyboardButton(text="⏹️ Завершить", callback_data="stop_group_test")])
    kb_markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
    
    # Отправляем изображение(я), если есть, как в обычных тестах
    try:
        if question.get('image') or question.get('images'):
            from aiogram.types import BufferedInputFile, InputMediaPhoto
            # Одно изображение
            if question.get('image'):
                image_bytes = question['image']['data']
                photo_file = BufferedInputFile(
                    file=image_bytes,
                    filename=question['image'].get('filename', 'question.png')
                )
                sent_q = await cb.message.answer_photo(
                    photo=photo_file,
                    caption=question_text,
                    parse_mode="HTML",
                    reply_markup=kb_markup
                )
            else:
                # Несколько изображений
                photo_files = []
                for img in question.get('images', []):
                    photo_files.append(BufferedInputFile(file=img['data'], filename=img.get('filename', 'question.png')))
                media_group = []
                media_group.append(InputMediaPhoto(media=photo_files[0], caption=question_text, parse_mode="HTML"))
                for pf in photo_files[1:]:
                    media_group.append(InputMediaPhoto(media=pf))
                sent_messages = await cb.message.answer_media_group(media_group)
                sent_q = sent_messages[0]
                # Клавиатура отдельным сообщением
                sent_kb = await cb.message.answer("Выберите действие:", reply_markup=kb_markup)
                message_manager.add_message(user_id, sent_kb.message_id)
        else:
            sent_q = await cb.message.answer(
                question_text,
                parse_mode="HTML",
                reply_markup=kb_markup
            )
        # Сохраняем ID сообщения с вопросом
        if user_id in user_test_state:
            user_test_state[user_id]['question_msg_id'] = sent_q.message_id
    except Exception:
        # Фоллбек на текст
        sent_q = await cb.message.answer(
            question_text,
            parse_mode="HTML",
            reply_markup=kb_markup
        )
        if user_id in user_test_state:
            user_test_state[user_id]['question_msg_id'] = sent_q.message_id


async def finish_group_test(cb: CallbackQuery, user_id: int):
    """Завершает тест группы и показывает результаты"""
    state = user_test_state.get(user_id, {})
    correct = state.get('correct_answers', 0)
    total = state.get('total_questions', 0)
    
    # Формируем текст результатов
    result_text = f"🎯 <b>Результаты задания группы</b>\n\n"
    result_text += f"📋 <b>Задание:</b> {state.get('group_task_title', '')}\n"
    result_text += f"✅ <b>Правильных ответов:</b> {correct} из {total}\n"
    
    percentage = (correct / total * 100) if total > 0 else 0
    result_text += f"📊 <b>Процент:</b> {percentage:.1f}%\n\n"
    
    if percentage >= 80:
        result_text += "🏆 <b>Отличный результат!</b>"
    elif percentage >= 60:
        result_text += "👍 <b>Хороший результат!</b>"
    else:
        result_text += "📚 <b>Есть над чем поработать!</b>"
    
    # Кнопки
    keyboard = [
        [InlineKeyboardButton(text="📋 К заданиям группы", callback_data="group_assignments")],
        [InlineKeyboardButton(text="⬅️ В главное меню", callback_data="to_main_menu")]
    ]
    
    await cb.message.answer(
        result_text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    
    # Очищаем состояние
    user_test_state.pop(user_id, None)


@router.callback_query(lambda c: c.data == "stop_group_test")
async def stop_group_test(cb: CallbackQuery):
    """Останавливает групповой тест"""
    await cb.answer()
    
    user_id = cb.from_user.id
    state = user_test_state.get(user_id, {})
    
    if not state.get('is_group_task'):
        await cb.message.answer("❌ Активного группового задания нет.")
        return
    
    # Завершаем тест досрочно
    await finish_group_test(cb, user_id)



@router.message(lambda m: user_test_state.get(m.from_user.id, {}).get('is_group_task', False))
async def handle_group_text_answer(m: types.Message):
    """Обрабатывает текстовые ответы на вопросы группового задания"""
    user_id = m.from_user.id
    state = user_test_state.get(user_id, {})
    
    if not state.get('is_group_task'):
        return
    
    answer_text = (m.text or "").strip()
    if not answer_text:
        await m.answer("❌ Пожалуйста, введите ответ.")
        return
    
    print(f"DEBUG: Получен текстовый ответ: '{answer_text}'")
    
    questions = state.get('questions', [])
    current_question = state.get('current_question', 0)
    
    if current_question >= len(questions):
        await m.answer("❌ Нет активного вопроса.")
        return
    
    question = questions[current_question]
    correct_answer = question.get('correct_answer', '').strip()
    
    print(f"DEBUG: Правильный ответ: '{correct_answer}'")
    
    # Проверяем правильность ответа
    is_correct = False
    if correct_answer and answer_text:
        # Для OGE правильный ответ часто содержит номера вариантов (например, "13" или "24")
        # Проверяем, совпадает ли ответ пользователя с правильным ответом
        if answer_text == correct_answer:
            is_correct = True
        # Также проверяем, содержит ли правильный ответ ответ пользователя
        elif answer_text in correct_answer and len(answer_text) >= 2:
            is_correct = True
        
        print(f"DEBUG: Результат сравнения: {is_correct}")
    
    # Обновляем счетчик правильных ответов
    if is_correct:
        state['correct_answers'] = state.get('correct_answers', 0) + 1
    
    # Логируем ответ и сохраняем его в БД
    try:
        log_question_answered(user_id, question['id'], answer_text, is_correct)
        save_test_answer(
            user_id=user_id,
            username=(getattr(m.from_user, "username", None) or m.from_user.full_name),
            test_type=_group_test_type(question),
            question_id=question['id'],
            question_text=question.get('question', ''),
            user_answer=answer_text,
            correct_answer=correct_answer,
            is_correct=is_correct,
            full_name=get_user_full_name(user_id)
        )
    except Exception:
        pass

    # Переходим к следующему вопросу
    state['current_question'] = current_question + 1
    user_test_state[user_id] = state
    
    # Показываем результат и следующий вопрос
    result_text = f"📋 <b>Задание группы: {state.get('group_task_title', '')}</b>\n\n"
    
    if is_correct:
        result_text += "✅ <b>Правильно!</b>\n\n"
    else:
        result_text += f"❌ <b>Неправильно.</b>\nВаш ответ: {answer_text}\nПравильный ответ: {correct_answer}\n\n"
    
    if state['current_question'] < len(questions):
        result_text += "➡️ Переходим к следующему вопросу..."
        await m.answer(result_text, parse_mode="HTML")
        
        # Показываем следующий вопрос
        await start_group_question_text(m, user_id)
    else:
        result_text += "🎯 Все вопросы пройдены!"
        await m.answer(result_text, parse_mode="HTML")
        
        # Завершаем тест
        await finish_group_test_text(m, user_id)


async def start_group_question_text(m: types.Message, user_id: int):
    """Показывает вопрос группового задания для текстового ввода"""
    state = user_test_state.get(user_id, {})
    questions = state.get('questions', [])
    current_question = state.get('current_question', 0)
    
    if current_question >= len(questions):
        # Тест завершен
        await finish_group_test_text(m, user_id)
        return
    
    question = questions[current_question]
    
    # Логируем старт вопроса (текстовая версия)
    try:
        log_question_started(user_id, _group_test_type(question), question['id'])
    except Exception:
        pass
    
    # Формируем текст вопроса
    question_text = f"📋 <b>Задание группы: {state.get('group_task_title', '')}</b>\n\n"
    question_text += f"❓ <b>Вопрос {current_question + 1} из {len(questions)}</b>\n\n"
    question_text += f"{question['question']}\n\n"
    
    # Добавляем варианты ответов если есть
    options = question.get('options', '')
    if options:
        question_text += f"{options}\n\n"
    
    # Для OGE вопросов ученик должен вводить ответы числами
    question_text += "\n\n💡 <b>Введите номера выбранных вариантов в одном сообщении (например: 13 или 24)</b>"
    
    # Кнопки управления
    keyboard = [
        [InlineKeyboardButton(text="⏹️ Завершить", callback_data="stop_group_test")]
    ]
    kb_markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
    
    # Отправка изображения(ий), если есть
    try:
        if question.get('image') or question.get('images'):
            from aiogram.types import BufferedInputFile, InputMediaPhoto
            if question.get('image'):
                image_bytes = question['image']['data']
                photo_file = BufferedInputFile(
                    file=image_bytes,
                    filename=question['image'].get('filename', 'question.png')
                )
                await m.answer_photo(photo=photo_file, caption=question_text, parse_mode="HTML", reply_markup=kb_markup)
            else:
                photo_files = []
                for img in question.get('images', []):
                    photo_files.append(BufferedInputFile(file=img['data'], filename=img.get('filename', 'question.png')))
                media_group = [InputMediaPhoto(media=photo_files[0], caption=question_text, parse_mode="HTML")]
                for pf in photo_files[1:]:
                    media_group.append(InputMediaPhoto(media=pf))
                await m.answer_media_group(media_group)
                # Клавиатура отдельным сообщением
                await m.answer("Выберите действие:", reply_markup=kb_markup)
        else:
            await m.answer(question_text, parse_mode="HTML", reply_markup=kb_markup)
    except Exception:
        await m.answer(question_text, parse_mode="HTML", reply_markup=kb_markup)


async def finish_group_test_text(m: types.Message, user_id: int):
    """Завершает тест группы и показывает результаты"""
    state = user_test_state.get(user_id, {})
    correct = state.get('correct_answers', 0)
    total = state.get('total_questions', 0)
    
    # Формируем текст результатов
    result_text = f"🎯 <b>Результаты задания группы</b>\n\n"
    result_text += f"📋 <b>Задание:</b> {state.get('group_task_title', '')}\n"
    result_text += f"✅ <b>Правильных ответов:</b> {correct} из {total}\n"
    
    percentage = (correct / total * 100) if total > 0 else 0
    result_text += f"📊 <b>Процент:</b> {percentage:.1f}%\n\n"
    
    if percentage >= 80:
        result_text += "🏆 <b>Отличный результат!</b>"
    elif percentage >= 60:
        result_text += "👍 <b>Хороший результат!</b>"
    else:
        result_text += "📚 <b>Есть над чем поработать!</b>"
    
    # Кнопки
    keyboard = [
        [InlineKeyboardButton(text="📋 К заданиям группы", callback_data="group_assignments")],
        [InlineKeyboardButton(text="⬅️ В главное меню", callback_data="to_main_menu")]
    ]
    
    await m.answer(
        result_text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    
    # Очищаем состояние
    user_test_state.pop(user_id, None)


@router.callback_query(lambda c: c.data == "to_main_menu")
async def to_main_menu(cb: CallbackQuery):
    # Очищаем состояние карточек при возврате в главное меню
    try:
        from bot.handlers.flashcards import user_flashcards_state
        user_id = cb.from_user.id
        if user_id in user_flashcards_state:
            user_flashcards_state[user_id] = {}
    except (ImportError, ModuleNotFoundError) as e:
        log_error(e, f"Import error clearing flashcards state in to_main_menu for user {cb.from_user.id}", user_id=cb.from_user.id)
    
    # Удаляем все старые сообщения перед показом главного меню
    await message_manager.delete_user_messages(cb.message.bot, cb.from_user.id, cb.message.chat.id)
    
    await cb.message.answer("Главное меню:", reply_markup=main_kb)
    await cb.answer()

# =========================
# 8. Подсказка к вопросу
# =========================
@router.callback_query(lambda c: c.data.startswith("hint_"))
async def show_hint(cb: CallbackQuery):
    # --- Лимит подсказок в день по тарифу ---
    user_id = cb.from_user.id
    plan = get_user_plan_code(user_id)
    limit = limits_for(plan)["test_hint_per_day"]
    ok, _left = consume_daily(user_id, "test_hint", limit)
    if not ok:
        try:
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💳 Тарифы и оплата", callback_data="to_tariffs")]])
            await cb.message.answer("Дневной лимит подсказок исчерпан. Оформи подписку для безлимита.", reply_markup=kb)
        except (ValueError, TypeError) as e:
            log_error(e, f"Data error sending tariff message in show_hint for user {cb.from_user.id}", user_id=cb.from_user.id)
        except (AttributeError, KeyError) as e:
            log_error(e, f"Unexpected error sending tariff message in show_hint for user {cb.from_user.id}", user_id=cb.from_user.id)
        await cb.answer()
        return
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
        except TelegramBadRequest as e:
            if "message is not modified" not in str(e).lower():
                log_error(e, f"BadRequest updating reply markup in show_hint for user {cb.from_user.id}", user_id=cb.from_user.id)
        except (ValueError, TypeError) as e:
            log_error(e, f"Data error updating reply markup in show_hint for user {cb.from_user.id}", user_id=cb.from_user.id)
        except (AttributeError, KeyError) as e:
            log_error(e, f"Unexpected error updating reply markup in show_hint for user {cb.from_user.id}", user_id=cb.from_user.id)
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
    and not user_learning_state.get(m.from_user.id, {}).get("awaiting_question")  # НЕ ждем вопрос учебника
))
async def check_test_answer(m: types.Message):
    state = user_test_state.get(m.from_user.id)
    idx = state["idx"]
    q_ids = state["q_ids"]
    q = get_question_by_id(q_ids[idx])
    
    # Проверяем, не отвечал ли уже пользователь на этот вопрос
    if state.get("answered", False):
        await m.answer("❌ Вы уже ответили на этот вопрос. Используйте кнопки «Объяснение» или «Далее».")
        return
    
    user_answer = ''.join(filter(str.isdigit, m.text))
    correct = ''.join(filter(str.isdigit, str(q.get("correct_answer", ""))))
    is_correct = user_answer == correct
    log_question_answered(m.from_user.id, q["id"], m.text, is_correct)  # --- ЛОГИРОВАНИЕ ОТВЕТА ---
    
    # Отмечаем, что пользователь ответил на вопрос
    user_test_state[m.from_user.id]["answered"] = True

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
    try:
        message_manager.add_message(m.from_user.id, sent.message_id)
    except Exception:
        pass
    # Обновим сетку статусов, если она есть
    try:
        grid_msg_id = user_test_state.get(m.from_user.id, {}).get("grid_msg_id")
        if grid_msg_id:
            test_type = user_test_state[m.from_user.id]["type"]
            q_ids = user_test_state[m.from_user.id]["q_ids"]
            kb = get_test_grid_kb(m.from_user.id, test_type, q_ids)
            # Безопасное редактирование с обработкой "message is not modified"
            try:
                await m.bot.edit_message_reply_markup(
                    chat_id=m.chat.id, 
                    message_id=grid_msg_id, 
                    reply_markup=kb
                )
            except TelegramBadRequest as e:
                if "message is not modified" not in str(e).lower():
                    log_error(e, f"Error updating grid markup after answer for user {m.from_user.id}", user_id=m.from_user.id)
            except (AttributeError, KeyError) as e:
                log_error(e, f"Error updating grid markup after answer for user {m.from_user.id}", user_id=m.from_user.id)
    except (ValueError, TypeError) as e:
        log_error(e, f"Data error updating grid in check_test_answer for user {m.from_user.id}", user_id=m.from_user.id)
    except (AttributeError, KeyError) as e:
        log_error(e, f"Unexpected error updating grid in check_test_answer for user {m.from_user.id}", user_id=m.from_user.id)
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
    # Убираем дубликаты одного и того же вопроса (могло быть несколько неверных попыток)
    mistake_q_ids_unique = list(dict.fromkeys([row[1] for row in mistakes]))
    user_test_state[user_id] = {
        "type": test_type,
        "idx": 0,
        "mistake_q_ids": mistake_q_ids_unique
    }
    await send_next_mistake_question(user_id, cb.message)
    await cb.answer()

# --- Отправка следующего ошибочного вопроса ---
async def send_next_mistake_question(user_id, message_obj):
    state = user_test_state.get(user_id)
    idx = state["idx"]
    q_ids = state["mistake_q_ids"]
    # Перед показом следующего ошибочного вопроса удалим только сообщения с результатами
    try:
        # Удаляем только сообщения с результатами ответов
        last_result_msg_id = state.get("last_result_msg_id")
        if last_result_msg_id:
            try:
                await message_obj.bot.delete_message(chat_id=message_obj.chat.id, message_id=last_result_msg_id)
            except Exception:
                pass
        last_question_msg_id = state.get("last_question_msg_id") 
        if last_question_msg_id:
            try:
                await message_obj.bot.delete_message(chat_id=message_obj.chat.id, message_id=last_question_msg_id)
            except Exception:
                pass
    except Exception:
        pass
    if idx >= len(q_ids):
        user_test_state.pop(user_id, None)
        sent_done = await message_obj.answer("Все ошибки в этом тесте исправлены! 👍")
        message_manager.add_message(user_id, sent_done.message_id)
        return
    q_id = q_ids[idx]
    
    # Используем новую функцию для получения вопроса с изображением
    from bot.services.test_sql import get_question_with_image
    q = get_question_with_image(q_id)
    
    if not q:
        await message_obj.answer("Ошибка: вопрос не найден.")
        return
        
    log_question_started(user_id, state["type"], q_id)  # --- ЛОГИРОВАНИЕ СТАРТА ---
    
    # Формируем текст вопроса
    formatted_q = _format_question_text(q['question'])
    msg = (
        f"Ошибка {idx+1} из {len(q_ids)} (Тест {state['type']})\n\n"
        f"{formatted_q}\n\n"
    )
    
    # Добавляем варианты ответов, если они есть
    if q['options']:
        options = q['options'].split('\n')
        msg += "\n".join([f"{i+1}. {opt}" for i, opt in enumerate(options)]) + "\n\n"
    
    msg += "Повтори попытку: введи номер(а) ответа:"
    
    used_hints = user_test_state.get(user_id, {}).get("used_hints", {}).get(state["type"], 0)
    hints_left = max(0, 10 - used_hints)
    kb = get_stop_test_kb(q_id, hints_left=hints_left)
    
    # Отправляем сообщение с изображением, если оно есть
    if q.get('image'):
        try:
            # Отправляем изображение с подписью
            from aiogram.types import BufferedInputFile
            
            # Создаём BufferedInputFile из байтов изображения
            image_bytes = q['image']['data']
            photo_file = BufferedInputFile(
                file=image_bytes,
                filename=q['image'].get('filename', 'question.png')
            )
            
            sent_q = await message_obj.answer_photo(
                photo=photo_file,
                caption=_to_html_with_code(msg),
                parse_mode="HTML",
                reply_markup=kb
            )
        except Exception as e:
            # Если не удалось отправить изображение, отправляем обычное сообщение
            from bot.utils_pkg_new.logger import log_error
            log_error(e, f"Failed to send image for mistake question {q_id}", user_id=user_id)
            sent_q = await message_obj.answer(_to_html_with_code(msg), parse_mode="HTML", reply_markup=kb)
    else:
        # Отправляем обычное сообщение без изображения
        sent_q = await message_obj.answer(_to_html_with_code(msg), parse_mode="HTML", reply_markup=kb)
    
    user_test_state[user_id]["last_question_msg_id"] = sent_q.message_id
    message_manager.add_message(user_id, sent_q.message_id)

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
        # Удаляем текущий id из очереди, чтобы не повторялся подряд; вернём в конец, если ещё неверно
        try:
            state["mistake_q_ids"].pop(idx)
        except (ValueError, IndexError) as e:
            log_error(e, f"Data error popping mistake_q_ids at index {idx} for user {m.from_user.id}", user_id=m.from_user.id)
        except (AttributeError, KeyError) as e:
            log_error(e, f"Unexpected error popping mistake_q_ids at index {idx} for user {m.from_user.id}", user_id=m.from_user.id)
        state["mistake_q_ids"].append(q_id)
        # idx не увеличиваем — следующий показ будет новый первый элемент очереди

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
    try:
        message_manager.add_message(m.from_user.id, sent.message_id)
    except Exception:
        pass
    # Переход к следующему вопросу ошибок — только после «Далее»
    # Обновим сетку статусов, если она показана в чате
    try:
        grid_msg_id = user_test_state.get(m.from_user.id, {}).get("grid_msg_id")
        if grid_msg_id:
            test_type = user_test_state[m.from_user.id]["type"]
            # В режиме ошибок глобального списка q_ids может не быть — пропустим
            q_ids = user_test_state[m.from_user.id].get("q_ids")
            if q_ids:
                kb = get_test_grid_kb(m.from_user.id, test_type, q_ids)
                # Безопасное редактирование с обработкой "message is not modified"
                try:
                    await m.bot.edit_message_reply_markup(
                        chat_id=m.chat.id, 
                        message_id=grid_msg_id, 
                        reply_markup=kb
                    )
                except TelegramBadRequest as e:
                    if "message is not modified" not in str(e).lower():
                        log_error(e, f"Error updating grid markup in mistake mode for user {m.from_user.id}", user_id=m.from_user.id)
                except (AttributeError, KeyError) as e:
                    log_error(e, f"Error updating grid markup in mistake mode for user {m.from_user.id}", user_id=m.from_user.id)
    except (ValueError, TypeError) as e:
        log_error(e, f"Data error updating grid in check_mistake_answer for user {m.from_user.id}", user_id=m.from_user.id)
    except (AttributeError, KeyError) as e:
        log_error(e, f"Unexpected error updating grid in check_mistake_answer for user {m.from_user.id}", user_id=m.from_user.id)

# =========================
# 10. Кнопка «К заданию» в подсказке — удаляет подсказку
# =========================
@router.callback_query(lambda c: c.data.startswith("back_to_question_"))
async def back_to_question(cb: CallbackQuery):
    try:
        await cb.message.delete()
    except (ValueError, TypeError) as e:
        log_error(e, f"Data error deleting message in back_to_question for user {cb.from_user.id}", user_id=cb.from_user.id)
        # Если не получилось удалить (нет прав или уже удалено) — просто скрываем кнопки
        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except (ValueError, TypeError) as e2:
            log_error(e2, f"Data error hiding keyboard in back_to_question for user {cb.from_user.id}", user_id=cb.from_user.id)
        except (AttributeError, KeyError) as e2:
            log_error(e2, f"Unexpected error hiding keyboard in back_to_question for user {cb.from_user.id}", user_id=cb.from_user.id)
    except (AttributeError, KeyError) as e:
        log_error(e, f"Unexpected error deleting message in back_to_question for user {cb.from_user.id}", user_id=cb.from_user.id)
        # Если не получилось удалить (нет прав или уже удалено) — просто скрываем кнопки
        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except (ValueError, TypeError) as e2:
            log_error(e2, f"Data error hiding keyboard in back_to_question for user {cb.from_user.id}", user_id=cb.from_user.id)
        except (AttributeError, KeyError) as e2:
            log_error(e2, f"Unexpected error hiding keyboard in back_to_question for user {cb.from_user.id}", user_id=cb.from_user.id)
    await cb.answer()

# --- КОНЕЦ ФАЙЛА ---
