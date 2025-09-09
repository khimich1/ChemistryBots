# bot/handlers/tests_oge.py
from __future__ import annotations

import base64
import io
from aiogram import Router, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.exceptions import TelegramBadRequest

from bot.handlers.menu import main_kb
from bot.utils import user_learning_state  # для проверки состояния учебника
# ОГЭ берём из НОВОГО сервиса, который читает shared/tests_updated.db
from bot.services.test_sql_oge import (
    get_all_tests_types, get_questions_by_type, get_question_by_id,
    mark_question_issue, copy_question_to_tests_bug,
)
# Ответы/прогресс храним в той же answer_db, но с ОФФСЕТОМ типа
from bot.services.answer_db import (
    save_test_answer, save_test_progress, load_test_progress, clear_test_progress,
    get_last_results_for_questions, reset_test_results, get_user_full_name,
    get_mistake_questions, set_answer_correct, log_question_started, log_question_answered, save_test_debug,
)
from bot.utils_pkg_new.logger import log_error
from bot.utils_pkg_new.telegram_error_handler import safe_edit_message, handle_telegram_errors
from bot.services.plan import get_user_plan_code, limits_for, consume_daily

router = Router()

# ── ключевые отличия ОГЭ ──────────────────────────────────────────────
CALLBACK_PREFIX = "oge"     # у всех callback_data будет префикс "oge_..."
OGE_TYPE_OFFSET = 1000      # чтобы test_type для ОГЭ не пересекался с ЕГЭ

def _t(x: int) -> int:
    """type для записи в answer_db (ЕГЭ и ОГЭ не путаются)"""
    return OGE_TYPE_OFFSET + int(x)

# отдельное состояние для сетки ОГЭ, чтобы не мешать EGE
user_test_state_oge: dict[int, dict] = {}

# ── ФУНКЦИИ ВАЛИДАЦИИ ──────────────────────────────────────────────────

def validate_test_type(test_type_str: str) -> int:
    """Безопасно извлекает и валидирует номер теста из callback_data"""
    try:
        test_type = int(test_type_str)
        if test_type < 1 or test_type > 50:  # разумные границы для ОГЭ
            raise ValueError(f"Test type {test_type} out of valid range [1-50]")
        return test_type
    except ValueError as e:
        log_error(f"Invalid test type: {test_type_str}, error: {e}")
        raise ValueError(f"Неверный номер теста: {test_type_str}")

def validate_question_id(q_id_str: str) -> int:
    """Безопасно извлекает и валидирует ID вопроса"""
    try:
        q_id = int(q_id_str)
        if q_id < 1:
            raise ValueError(f"Question ID {q_id} must be positive")
        return q_id
    except ValueError as e:
        log_error(f"Invalid question ID: {q_id_str}, error: {e}")
        raise ValueError(f"Неверный ID вопроса: {q_id_str}")

def validate_question_number(number_str: str, max_questions: int = 30) -> int:
    """Безопасно извлекает и валидирует номер вопроса"""
    try:
        number = int(number_str)
        if number < 1 or number > max_questions:
            raise ValueError(f"Question number {number} out of range [1-{max_questions}]")
        return number
    except ValueError as e:
        log_error(f"Invalid question number: {number_str}, error: {e}")
        raise ValueError(f"Неверный номер вопроса: {number_str}")

def validate_user_answer(answer_text: str, max_digits: int = 10) -> str:
    """Валидирует ответ пользователя"""
    if not isinstance(answer_text, str):
        raise ValueError("Ответ должен быть текстом")
    
    # Извлекаем только цифры
    digits = ''.join(filter(str.isdigit, answer_text))
    
    if not digits:
        raise ValueError("В ответе нет цифр. Введите номер(а) ответа.")
    
    if len(digits) > max_digits:
        raise ValueError(f"Слишком много цифр в ответе (максимум {max_digits})")
    
    return digits



def safe_get_state(user_id: int) -> dict:
    """Безопасно получает состояние пользователя"""
    state = user_test_state_oge.get(user_id)
    if not state:
        raise ValueError(f"Состояние пользователя {user_id} не найдено")
    return state

def safe_get_question_data(state: dict) -> tuple[int, list, dict]:
    """Безопасно извлекает данные вопроса из состояния"""
    if "idx" not in state:
        raise ValueError("Индекс вопроса не найден в состоянии")
    if "q_ids" not in state:
        raise ValueError("Список вопросов не найден в состоянии")
    
    idx = state["idx"]
    q_ids = state["q_ids"]
    
    if not q_ids:
        raise ValueError("Список вопросов пуст")
    
    if idx >= len(q_ids):
        raise ValueError(f"Индекс вопроса {idx} выходит за пределы списка ({len(q_ids)})")
    
    q = get_question_by_id(q_ids[idx])
    if not q:
        raise ValueError(f"Вопрос с ID {q_ids[idx]} не найден")
    
    return idx, q_ids, q

def _is_base64_image(text: str) -> bool:
    """Проверяет, является ли текст base64 изображением"""
    return text.strip().startswith('data:image/') and ';base64,' in text

def _extract_base64_data(data_url: str) -> tuple[str, bytes]:
    """Извлекает MIME тип и данные из base64 data URL"""
    try:
        # Формат: data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAA...
        header, encoded = data_url.split(',', 1)
        mime_type = header.split(':')[1].split(';')[0]  # image/png
        image_data = base64.b64decode(encoded)
        return mime_type, image_data
    except Exception as e:
        log_error(f"Ошибка декодирования base64: {e}, data_url: {data_url[:100]}...")
        return "image/png", b""

def _send_base64_image_as_photo(bot, chat_id: int, base64_text: str, caption: str = "") -> bool:
    """Отправляет base64 изображение как фото в Telegram (синхронная версия)"""
    try:
        if not _is_base64_image(base64_text):
            return False
            
        mime_type, image_data = _extract_base64_data(base64_text)
        image_stream = io.BytesIO(image_data)
        
        # Определяем расширение файла
        ext = mime_type.split('/')[-1] if '/' in mime_type else 'png'
        image_stream.name = f"image.{ext}"
        
        # Отправляем как фото
        bot.send_photo(
            chat_id=chat_id,
            photo=image_stream,
            caption=caption,
            parse_mode="HTML"
        )
        return True
    except Exception as e:
        log_error(f"Ошибка отправки base64 изображения: {e}")
        return False

async def _send_base64_image_as_photo_async(bot, chat_id: int, base64_text: str, caption: str = "") -> bool:
    """Отправляет base64 изображение как фото в Telegram (асинхронная версия)"""
    try:
        if not _is_base64_image(base64_text):
            return False
            
        mime_type, image_data = _extract_base64_data(base64_text)
        image_stream = io.BytesIO(image_data)
        
        # Определяем расширение файла
        ext = mime_type.split('/')[-1] if '/' in mime_type else 'png'
        image_stream.name = f"image.{ext}"
        
        # Отправляем как фото
        await bot.send_photo(
            chat_id=chat_id,
            photo=image_stream,
            caption=caption,
            parse_mode="HTML"
        )
        return True
    except Exception as e:
        log_error(f"Ошибка отправки base64 изображения: {e}")
        return False

# ── клавиатуры ────────────────────────────────────────────────────────
def get_tests_types_kb(with_menu: bool = False, include_back: bool = False) -> InlineKeyboardMarkup:
    types_list = get_all_tests_types()
    keyboard = [
        [InlineKeyboardButton(text=f"Тест {t}", callback_data=f"{CALLBACK_PREFIX}_choose_test_{t}")]
        for t in types_list if t not in (None, "")
    ]
    # --- Кнопка "Работа над ошибками" ---
    keyboard.append([InlineKeyboardButton(text="💡 Работа над ошибками", callback_data=f"{CALLBACK_PREFIX}_work_on_mistakes")])
    if include_back:
        keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"{CALLBACK_PREFIX}_tests_go_back")])
    if with_menu:
        keyboard.append([InlineKeyboardButton(text="⬅️ В главное меню", callback_data="to_main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_test_grid_kb(user_id: int, test_type: int, q_ids: list[int]) -> InlineKeyboardMarkup:
    """
    Та же сетка 3×10, но callback'и с префиксом 'oge_' и прогресс читается по _t(test_type).
    """
    status = get_last_results_for_questions(user_id, _t(test_type), q_ids)

    def _label(i0: int) -> tuple[str, str]:
        num = i0 + 1
        st = status.get(q_ids[i0])
        mark = "✅" if st == 1 else "❌" if st == 0 else "⬜"
        return f"{num}{mark}", f"{CALLBACK_PREFIX}_jump_{test_type}_{num}"

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
        InlineKeyboardButton(text="🔄 Начать заново", callback_data=f"{CALLBACK_PREFIX}_restart_test_{test_type}"),
        InlineKeyboardButton(text="📊 Статистика",   callback_data=f"{CALLBACK_PREFIX}_show_stats_{test_type}"),
    ])
    rows.append([InlineKeyboardButton(text="🧹 Скрыть таблицу", callback_data=f"{CALLBACK_PREFIX}_hide_grid")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

# ── вход в раздел ОГЭ ─────────────────────────────────────────────────
@router.message(lambda m: (m.text or "").strip().lower() == "🧪 тестовая часть огэ по химии")
async def show_oge_tests_types_menu(m: types.Message):
    # Берём готовый красивый текст из ege-хэндлера, чтобы не дублировать
    from .tests import tests_instruction_text
    await m.answer(tests_instruction_text(), parse_mode="HTML")
    await m.answer("Выбери номер ОГЭ-теста:", reply_markup=get_tests_types_kb(with_menu=True, include_back=True))

# ── выбор теста: показать/восстановить сетку ──────────────────────────
@router.callback_query(lambda c: c.data.startswith(f"{CALLBACK_PREFIX}_choose_test_"))
async def start_test(cb: CallbackQuery):
    try:
        # Валидируем callback_data
        # Формат: oge_choose_test_{test_type}
        if not cb.data.startswith(f"{CALLBACK_PREFIX}_choose_test_"):
            raise ValueError(f"Неверный префикс callback данных: {cb.data}")
        
        # Извлекаем test_type из конца строки
        test_type_str = cb.data.replace(f"{CALLBACK_PREFIX}_choose_test_", "")
        if not test_type_str:
            raise ValueError("Не найден номер теста в callback данных")
        
        test_type = validate_test_type(test_type_str)
    except ValueError as e:
        await cb.answer(f"Ошибка: {str(e)}")
        log_error(f"Validation error in start_test for user {cb.from_user.id}: {e}")
        return

    # удалить предыдущую сетку, если была
    try:
        prev = user_test_state_oge.get(cb.from_user.id) or {}
        prev_grid_id = prev.get("grid_msg_id")
        if prev_grid_id:
            await cb.message.bot.delete_message(chat_id=cb.message.chat.id, message_id=prev_grid_id)
    except Exception:
        pass

    # попытка восстановить прогресс (ОБРАТИ: _t(test_type))
    idx, q_ids = load_test_progress(cb.from_user.id, _t(test_type))
    if idx is not None and q_ids:
        kb = get_test_grid_kb(cb.from_user.id, test_type, q_ids)
        sent = await cb.message.answer(
            f"ОГЭ. Тест {test_type}. Выбери номер задания или нажми «Начать заново»:",
            reply_markup=kb
        )
        st = user_test_state_oge.setdefault(cb.from_user.id, {})
        st.update({"type": test_type, "idx": idx, "q_ids": q_ids, "grid_msg_id": sent.message_id})
        await cb.answer()
        return

    # если прогресса нет — стартуем с нуля из БД ОГЭ
    questions = get_questions_by_type(test_type)
    if not questions:
        await cb.message.answer("Нет вопросов для этого ОГЭ-теста.")
        await cb.answer()
        return

    user_test_state_oge[cb.from_user.id] = {
        "type": test_type,
        "idx": 0,
        "q_ids": [q["id"] for q in questions],
    }
    clear_test_progress(cb.from_user.id, _t(test_type))
    grid_kb = get_test_grid_kb(cb.from_user.id, test_type, user_test_state_oge[cb.from_user.id]["q_ids"])
    sent_grid = await cb.message.answer(
        f"ОГЭ. Тест {test_type}. Выбери номер задания или нажми «Начать заново»:",
        reply_markup=grid_kb
    )
    user_test_state_oge[cb.from_user.id]["grid_msg_id"] = sent_grid.message_id
    await cb.answer()

# ── вспомогательные функции ────────────────────────────────────────────
import html
import re

def _truncate_message(text: str, max_length: int = 4000) -> str:
    """Обрезает сообщение до безопасной длины для Telegram"""
    if len(text) <= max_length:
        return text
    
    # Ищем место для обрезки (предпочтительно перед переносом строки)
    cut_point = max_length
    for i in range(max_length, max(0, max_length - 200), -1):
        if text[i] == '\n':
            cut_point = i
            break
    
    truncated = text[:cut_point].rstrip()
    return truncated + "\n\n[Сообщение обрезано из-за длины]"

def _format_question_text(text: str) -> str:
    """Форматирование текста задания с переносами строк"""
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

def _to_html_with_code(text: str) -> str:
    """Рендер текста с поддержкой блоков кода в тройных кавычках"""
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

# ── клавиатуры для вопросов ────────────────────────────────────────────
def get_stop_test_kb(q_id, hints_left: int | None = None):
    hint_text = "💡 Подсказка" if hints_left is None else f"💡 Подсказка ({hints_left})"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=hint_text, callback_data=f"{CALLBACK_PREFIX}_hint_{q_id}")],
            [InlineKeyboardButton(text="⏹️ Стоп тест", callback_data=f"{CALLBACK_PREFIX}_stop_test")],
            [InlineKeyboardButton(text="❗ Пожаловаться", callback_data=f"{CALLBACK_PREFIX}_report_{q_id}")]
        ]
    )

def get_hint_kb(q_id: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ К заданию", callback_data=f"{CALLBACK_PREFIX}_back_to_question_{q_id}")]
        ]
    )

def get_result_kb(q_id: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🧠 Объяснение", callback_data=f"{CALLBACK_PREFIX}_explain_{q_id}")],
                         [InlineKeyboardButton(text="➡️ Далее", callback_data=f"{CALLBACK_PREFIX}_next_q_{q_id}")]]
    )

def get_next_kb(q_id: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="➡️ Далее", callback_data=f"{CALLBACK_PREFIX}_next_q_{q_id}")]]
    )

def get_explain_only_kb(q_id: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🧠 Объяснение", callback_data=f"{CALLBACK_PREFIX}_explain_{q_id}")]]
    )

# ── обработчики ────────────────────────────────────────────────────────
@router.callback_query(lambda c: c.data.startswith(f"{CALLBACK_PREFIX}_jump_"))
async def jump_to_question(cb: CallbackQuery):
    try:
        # Формат: oge_jump_{test_type}_{number}
        parts = cb.data.split("_")
        if len(parts) != 4:
            raise ValueError(f"Неверное количество частей в callback данных: {len(parts)}, ожидается 4")
        if not cb.data.startswith(f"{CALLBACK_PREFIX}_jump_"):
            raise ValueError(f"Неверный префикс callback данных: {cb.data}")
        test_type = validate_test_type(parts[2])
        number = validate_question_number(parts[3])
    except ValueError as e:
        await cb.answer(f"Ошибка: {str(e)}")
        log_error(f"Validation error in jump_to_question for user {cb.from_user.id}: {e}")
        return
    _idx, q_ids = load_test_progress(cb.from_user.id, _t(test_type))
    if not q_ids:
        questions = get_questions_by_type(test_type)
        if not questions:
            await cb.message.answer("Нет вопросов для этого теста.")
            await cb.answer()
            return
        q_ids = [q["id"] for q in questions]
    number = min(number, len(q_ids))
    
    # Удаляем предыдущее сообщение-вопрос, если было
    try:
        st_prev = user_test_state_oge.get(cb.from_user.id) or {}
        last_q_msg_id = st_prev.pop("last_question_msg_id", None)
        if last_q_msg_id:
            await cb.message.bot.delete_message(chat_id=cb.message.chat.id, message_id=last_q_msg_id)
    except Exception:
        pass

    prev = user_test_state_oge.get(cb.from_user.id) or {}
    user_test_state_oge[cb.from_user.id] = {
        "type": test_type,
        "idx": number - 1,
        "q_ids": q_ids,
        "grid_msg_id": prev.get("grid_msg_id"),
        "used_hints": prev.get("used_hints", {}),
    }
    await send_next_test_question(cb.from_user.id, cb.message, is_callback=True)
    await cb.answer()

async def send_next_test_question(user_id, message_obj, is_callback=False):
    state = user_test_state_oge.get(user_id)
    if not state:
        return
    idx = state["idx"]
    q_ids = state["q_ids"]
    if idx >= len(q_ids):
        user_test_state_oge.pop(user_id, None)
        await message_obj.answer("Тест завершён! Возвращаюсь в меню.")
        return
    
    q = get_question_by_id(q_ids[idx])
    log_question_started(user_id, _t(state["type"]), q["id"])  # --- ЛОГИРОВАНИЕ СТАРТА ---
    
    # Подсказки: максимум 10 на 30 вопросов одного теста
    used_hints = user_test_state_oge.get(user_id, {}).get("used_hints", {}).get(state["type"], 0)
    hints_left = max(0, 10 - used_hints)
    kb = get_stop_test_kb(q['id'], hints_left=hints_left)
    
    # Обрабатываем вопрос - проверяем наличие изображений
    question_text = q['question']
    filename = q.get('filename', '')
    
    # Проверяем, есть ли упоминание рисунка в вопросе
    has_image_reference = any(word in question_text.lower() for word in ['рисунке', 'схеме', 'диаграмме', 'графике'])
    
    # Форматируем вопрос
    formatted_q = _format_question_text(question_text)
    
    # Обрабатываем варианты ответов
    # В базе данных варианты могут быть в одной строке, разделенные цифрами
    options_text = q['options']
    image_options = []
    text_options = []
    
    # Ищем варианты ответов по паттерну: цифра) текст или цифра) data:image/...
    import re
    option_pattern = r'(\d+)\)\s*(.*?)(?=\d+\)|$)'
    matches = re.findall(option_pattern, options_text, re.DOTALL)
    
    for i, (num, content) in enumerate(matches):
        content = content.strip()
        if not content:  # Пропускаем пустые варианты
            continue
            
        if _is_base64_image(content):
            image_options.append((int(num), content))
        else:
            text_options.append(f"{num}) {content}")
    
    # Формируем полное сообщение с вопросом и вариантами ответов
    full_message = f"Вопрос {idx+1} из {len(q_ids)} (ОГЭ. Тест {state['type']})\n\n{formatted_q}"
    
    # Варианты ответов добавляются ниже с нумерацией
    
    # Добавляем инструкцию по вводу ответа
    if image_options or text_options:
        full_message += "\n\nВведите номер(а) ответа (например: 2 или 13):"
        
        # Добавляем варианты ответов (они уже пронумерованы в БД)
        if text_options:
            full_message += "\n\n" + "\n".join(text_options)
    
    # Если есть упоминание рисунка, добавляем информацию об изображении
    if has_image_reference and filename:
        full_message += f"\n\n📷 [Изображение: {filename}]"
    elif has_image_reference:
        full_message += "\n\n📷 [Изображение отсутствует]"
    
    # Отправляем полное сообщение
    html_message = _to_html_with_code(full_message)
    safe_message = _truncate_message(html_message, 4000)
    
    sent_q = await message_obj.answer(safe_message, parse_mode="HTML", reply_markup=kb)
    user_test_state_oge[user_id]["last_question_msg_id"] = sent_q.message_id
    
    # Если сообщение было обрезано, отправляем продолжение
    if len(html_message) > 4000:
        remaining_text = html_message[4000:]
        remaining_safe = _truncate_message(remaining_text, 4000)
        await message_obj.answer(remaining_safe, parse_mode="HTML")
    
    # Отправляем изображения как фото (если есть)
    for option_num, base64_img in image_options:
        caption = f"Вариант {option_num}"
        success = await _send_base64_image_as_photo_async(message_obj.bot, message_obj.chat.id, base64_img, caption)
        if not success:
            # Если не удалось отправить как фото, отправляем как текст
            await message_obj.answer(f"Вариант {option_num}: [Изображение]")

@router.callback_query(lambda c: c.data == f"{CALLBACK_PREFIX}_stop_test")
async def stop_test(cb: CallbackQuery):
    state = user_test_state_oge.pop(cb.from_user.id, None)
    
    # --- Если работаем над ошибками ---
    if state and "mistake_q_ids" in state:
        await cb.message.answer(
            "Разбор ошибок завершён! Возвращаюсь в раздел тестов.",
            reply_markup=get_tests_types_kb(with_menu=True)
        )
    elif state:
        save_test_progress(cb.from_user.id, _t(state["type"]), state["idx"], state["q_ids"])
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

@router.callback_query(lambda c: c.data == f"{CALLBACK_PREFIX}_hide_grid")
async def hide_grid(cb: CallbackQuery):
    try:
        st = user_test_state_oge.get(cb.from_user.id) or {}
        grid_id = st.pop("grid_msg_id", None)
        if grid_id:
            await cb.message.bot.delete_message(chat_id=cb.message.chat.id, message_id=grid_id)
            user_test_state_oge[cb.from_user.id] = st
    except Exception:
        pass
    await cb.answer()

@router.callback_query(lambda c: c.data.startswith(f"{CALLBACK_PREFIX}_restart_test_"))
async def restart_test(cb: CallbackQuery):
    test_type = int(cb.data.split("_")[-1])
    questions = get_questions_by_type(test_type)
    if not questions:
        await cb.message.answer("Нет вопросов для этого теста.")
        await cb.answer()
        return
    
    clear_test_progress(cb.from_user.id, _t(test_type))
    reset_test_results(cb.from_user.id, _t(test_type))
    
    prev = user_test_state_oge.get(cb.from_user.id) or {}
    user_test_state_oge[cb.from_user.id] = {
        "type": test_type,
        "idx": 0,
        "q_ids": [q["id"] for q in questions],
        "grid_msg_id": prev.get("grid_msg_id"),
        "used_hints": prev.get("used_hints", {}),
    }
    
    # Перерисуем таблицу со сброшенными статусами
    try:
        grid_id = user_test_state_oge[cb.from_user.id].get("grid_msg_id")
        kb = get_test_grid_kb(cb.from_user.id, test_type, user_test_state_oge[cb.from_user.id]["q_ids"])
        if grid_id:
            # Безопасное редактирование с обработкой "message is not modified"
            try:
                await cb.message.bot.edit_message_reply_markup(
                    chat_id=cb.message.chat.id, 
                    message_id=grid_id, 
                    reply_markup=kb
                )
            except TelegramBadRequest as e:
                if "message is not modified" not in str(e).lower():
                    log_error(e, f"Error updating grid markup for user {cb.from_user.id}")
        else:
            sent = await cb.message.answer(f"ОГЭ. Тест {test_type}. Выбери номер задания или нажми «Начать заново»:", reply_markup=kb)
            user_test_state_oge[cb.from_user.id]["grid_msg_id"] = sent.message_id
    except Exception as e:
        log_error(e, f"Error in reset_test for user {cb.from_user.id}")
    await cb.answer()

@router.callback_query(lambda c: c.data.startswith(f"{CALLBACK_PREFIX}_back_to_question_"))
async def back_to_question(cb: CallbackQuery):
    try:
        await cb.message.delete()
    except Exception:
        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
    await cb.answer()

@router.callback_query(lambda c: c.data.startswith(f"{CALLBACK_PREFIX}_next_q_"))
async def go_next_question(cb: CallbackQuery):
    try:
        parts = cb.data.split("_")
        q_id = int(parts[-1]) if parts and parts[-1].isdigit() else None
        msg_text = (cb.message.text or "").strip()
        is_explanation = msg_text.startswith("🧠 Объяснение")
        if is_explanation:
            try:
                await cb.message.delete()
            except Exception:
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

    st = user_test_state_oge.get(cb.from_user.id)
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

# ── обработка ответов пользователя ────────────────────────────────────
@router.message(lambda m: (
    m.from_user.id in user_test_state_oge
    and "q_ids" in user_test_state_oge[m.from_user.id]
    and isinstance(getattr(m, "text", None), str)
    and any(ch.isdigit() for ch in m.text)
    and not user_learning_state.get(m.from_user.id, {}).get("awaiting_question")  # НЕ ждем вопрос учебника
))
async def check_test_answer(m: types.Message):
    try:
        # Безопасно получаем состояние и данные вопроса
        state = safe_get_state(m.from_user.id)
        idx, q_ids, q = safe_get_question_data(state)
        
        # Валидируем ответ пользователя
        user_answer = validate_user_answer(m.text)
        correct = ''.join(filter(str.isdigit, str(q.get("correct_answer", ""))))
        is_correct = user_answer == correct
        log_question_answered(m.from_user.id, q["id"], m.text, is_correct)  # --- ЛОГИРОВАНИЕ ОТВЕТА ---
        
    except ValueError as e:
        await m.answer(f"❌ Ошибка: {str(e)}")
        log_error(f"Validation error in check_test_answer for user {m.from_user.id}: {e}")
        return
    except Exception as e:
        await m.answer("❌ Произошла ошибка при обработке ответа. Попробуйте ещё раз.")
        log_error(f"Unexpected error in check_test_answer for user {m.from_user.id}: {e}")
        return

    # Сохраняем ответ в базу данных
    save_test_answer(
        m.from_user.id,
        getattr(m.from_user, "username", None) or m.from_user.full_name,
        _t(state["type"]),  # используем _t() для offset
        q["id"],
        q["question"],
        m.text,
        q.get("correct_answer", ""),
        is_correct,
        full_name=get_user_full_name(m.from_user.id)
    )

    # Сообщение с результатом
    resp_lines = [
        "✅ Верно!" if is_correct else "❌ Неверно.",
        f"Твой ответ: {user_answer if user_answer else m.text.strip()}",
        f"Правильный ответ: {correct}",
        "",
        f"Вопрос {idx+1} из {len(q_ids)}",
    ]
    resp = "\n".join(resp_lines)
    sent = await m.answer(_to_html_with_code(resp), parse_mode="HTML", reply_markup=get_result_kb(q["id"]))
    user_test_state_oge[m.from_user.id]["last_result_msg_id"] = sent.message_id
    
    # Обновим сетку статусов, если она есть
    try:
        grid_msg_id = user_test_state_oge.get(m.from_user.id, {}).get("grid_msg_id")
        if grid_msg_id:
            test_type = user_test_state_oge[m.from_user.id]["type"]
            q_ids = user_test_state_oge[m.from_user.id]["q_ids"]
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
                    log_error(e, f"Error updating grid markup after answer for user {m.from_user.id}")
    except Exception as e:
        log_error(e, f"Error updating grid after answer for user {m.from_user.id}")

# ── подсказки и объяснения ─────────────────────────────────────────────
@router.callback_query(lambda c: c.data.startswith(f"{CALLBACK_PREFIX}_hint_"))
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
        except Exception as e:
            log_error(f"Ошибка отправки сообщения о тарифах: {e}")
        await cb.answer()
        return
    
    try:
        # Формат: oge_hint_{q_id}
        if not cb.data.startswith(f"{CALLBACK_PREFIX}_hint_"):
            raise ValueError(f"Неверный префикс callback данных: {cb.data}")
        
        # Извлекаем q_id из конца строки
        q_id_str = cb.data.replace(f"{CALLBACK_PREFIX}_hint_", "")
        if not q_id_str:
            raise ValueError("Не найден ID вопроса в callback данных")
        
        q_id = validate_question_id(q_id_str)
        q = get_question_by_id(q_id)
        if not q:
            await cb.answer("Вопрос не найден")
            return
    except ValueError as e:
        await cb.answer(f"Ошибка: {str(e)}")
        log_error(f"Validation error in show_hint for user {cb.from_user.id}: {e}")
        return
    
    # Подсказки: проверяем лимит 10 на тест (30 вопросов)
    st = user_test_state_oge.get(cb.from_user.id)
    test_type = st.get("type") if st else None
    used_map = user_test_state_oge.setdefault(cb.from_user.id, {}).setdefault("used_hints", {})
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
                log_error(e, f"BadRequest updating reply markup in show_hint for user {cb.from_user.id}")
    else:
        await cb.message.answer("Для этого задания нет подсказки.")
    await cb.answer()

@router.callback_query(lambda c: c.data.startswith(f"{CALLBACK_PREFIX}_explain_"))
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
        except Exception as e:
            log_error(f"Ошибка отправки сообщения о тарифах: {e}")
        await cb.answer()
        return
    
    try:
        # Формат: oge_explain_{q_id}
        if not cb.data.startswith(f"{CALLBACK_PREFIX}_explain_"):
            raise ValueError(f"Неверный префикс callback данных: {cb.data}")
        
        # Извлекаем q_id из конца строки
        q_id_str = cb.data.replace(f"{CALLBACK_PREFIX}_explain_", "")
        if not q_id_str:
            raise ValueError("Не найден ID вопроса в callback данных")
        
        q_id = validate_question_id(q_id_str)
        q = get_question_by_id(q_id)
        if not q:
            await cb.answer("Вопрос не найден")
            return
    except ValueError as e:
        await cb.answer(f"Ошибка: {str(e)}")
        log_error(f"Validation error in show_explanation for user {cb.from_user.id}: {e}")
        return
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

# ── жалобы на вопросы ──────────────────────────────────────────────────
@router.callback_query(lambda c: c.data and c.data.startswith(f"{CALLBACK_PREFIX}_report_") and c.data[8:].isdigit())
async def report_question(cb: CallbackQuery):
    q_id = int(cb.data.split("_")[-1])
    # Пытаемся удалить сообщение-вопрос сразу при нажатии «Пожаловаться»
    try:
        st = user_test_state_oge.get(cb.from_user.id) or {}
        last_q_id = st.pop("last_question_msg_id", None)
        if last_q_id:
            await cb.message.bot.delete_message(chat_id=cb.message.chat.id, message_id=last_q_id)
    except Exception:
        pass
    
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📝 Проблема с заданием", callback_data=f"{CALLBACK_PREFIX}_report_reason_{q_id}_task")],
            [InlineKeyboardButton(text="💡 Проблема с подсказкой", callback_data=f"{CALLBACK_PREFIX}_report_reason_{q_id}_hint")],
            [InlineKeyboardButton(text="✅ Проблема с ответом", callback_data=f"{CALLBACK_PREFIX}_report_reason_{q_id}_answer")],
            [InlineKeyboardButton(text="✍️ Свой вариант", callback_data=f"{CALLBACK_PREFIX}_report_reason_{q_id}_custom")],
        ]
    )
    await cb.message.answer("Что именно смутило в этом задании?", reply_markup=kb)
    await cb.answer()

@router.callback_query(lambda c: c.data.startswith(f"{CALLBACK_PREFIX}_report_reason_"))
async def report_reason(cb: CallbackQuery):
    parts = cb.data.split("_")
    # ['oge', 'report', 'reason', '{q_id}', '{code}']
    q_id = int(parts[3])
    code = parts[4]
    reason_map = {
        "task": "Проблема с заданием",
        "hint": "Проблема с подсказкой",
        "answer": "Проблема с ответом",
    }
    if code == "custom":
        # Просим текст причины в свободной форме
        st = user_test_state_oge.get(cb.from_user.id) or {}
        st["awaiting_issue_text"] = {"q_id": q_id}
        user_test_state_oge[cb.from_user.id] = st
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
    st = user_test_state_oge.get(cb.from_user.id)
    if not st:
        await cb.answer()
        return
    
    if "mistake_q_ids" in st:
        # режим работы над ошибками: удаляем текущий id из списка и показываем следующий
        try:
            st["mistake_q_ids"].remove(q_id)
        except ValueError as e:
            log_error(f"ValueError removing q_id {q_id} from mistake_q_ids for user {cb.from_user.id}: {e}")
        except Exception as e:
            log_error(f"Unexpected error removing q_id {q_id} from mistake_q_ids for user {cb.from_user.id}: {e}")
        user_test_state_oge[cb.from_user.id] = st
        await send_next_mistake_question(cb.from_user.id, cb.message)
    else:
        # обычный режим: двигаем индекс
        st["idx"] = st.get("idx", 0) + 1
        user_test_state_oge[cb.from_user.id] = st
        await send_next_test_question(cb.from_user.id, cb.message, is_callback=True)
    await cb.answer()

# ── обработчик текста причины (свой вариант) ──────────────────────────
@router.message(lambda m: (
    m.from_user.id in user_test_state_oge
    and isinstance(getattr(m, "text", None), str)
    and user_test_state_oge[m.from_user.id].get("awaiting_issue_text") is not None
))
async def report_custom_text(m: types.Message):
    st = user_test_state_oge.get(m.from_user.id) or {}
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
            log_error(f"ValueError removing q_id {q_id} from mistake_q_ids in report_custom_text for user {m.from_user.id}: {e}")
        except Exception as e:
            log_error(f"Unexpected error removing q_id {q_id} from mistake_q_ids in report_custom_text for user {m.from_user.id}: {e}")
        user_test_state_oge[m.from_user.id] = st
        await send_next_mistake_question(m.from_user.id, m)
    else:
        st["idx"] = st.get("idx", 0) + 1
        user_test_state_oge[m.from_user.id] = st
        await send_next_test_question(m.from_user.id, m)

# ── статистика ─────────────────────────────────────────────────────────
def generate_test_stats(user_id: int, test_type: int, q_ids: list[int]) -> str:
    """Генерирует статистику прохождения теста."""
    status = get_last_results_for_questions(user_id, _t(test_type), q_ids)
    
    total = len(q_ids)
    correct = sum(1 for st in status.values() if st == 1)
    incorrect = sum(1 for st in status.values() if st == 0)
    not_attempted = total - correct - incorrect
    
    if total == 0:
        return "📊 <b>Статистика ОГЭ. Тест {test_type}</b>\n\nНет данных для анализа."
    
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
        f"📊 <b>Статистика ОГЭ. Тест {test_type}</b>\n\n"
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
            [InlineKeyboardButton(text="📋 К таблице", callback_data=f"{CALLBACK_PREFIX}_back_to_grid_{test_type}")],
            [InlineKeyboardButton(text="⬅️ В главное меню", callback_data="to_main_menu")],
        ]
    )

@router.callback_query(lambda c: c.data.startswith(f"{CALLBACK_PREFIX}_show_stats_"))
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
    st = user_test_state_oge.setdefault(cb.from_user.id, {})
    st["stats_msg_id"] = sent.message_id
    user_test_state_oge[cb.from_user.id] = st
    
    await cb.answer()

@router.callback_query(lambda c: c.data.startswith(f"{CALLBACK_PREFIX}_back_to_grid_"))
async def back_to_grid(cb: CallbackQuery):
    try:
        test_type = int(cb.data.split("_")[-1])
    except ValueError:
        await cb.answer("Ошибка: неверный номер теста.")
        return
    
    # Удаляем сообщение со статистикой
    try:
        st = user_test_state_oge.get(cb.from_user.id) or {}
        stats_msg_id = st.pop("stats_msg_id", None)
        if stats_msg_id:
            await cb.message.bot.delete_message(chat_id=cb.message.chat.id, message_id=stats_msg_id)
            user_test_state_oge[cb.from_user.id] = st
    except Exception:
        pass
    
    # Получаем список вопросов для теста
    questions = get_questions_by_type(test_type)
    if not questions:
        await cb.message.answer("Нет вопросов для этого теста.")
        await cb.answer()
        return
    
    q_ids = [q["id"] for q in questions]
    
    # Показываем таблицу снова
    grid_kb = get_test_grid_kb(cb.from_user.id, test_type, q_ids)
    sent = await cb.message.answer(f"ОГЭ. Тест {test_type}. Выбери номер задания или нажми «Начать заново»:", reply_markup=grid_kb)
    
    # Сохраняем ID сообщения-сетки
    st = user_test_state_oge.setdefault(cb.from_user.id, {})
    st["grid_msg_id"] = sent.message_id
    user_test_state_oge[cb.from_user.id] = st
    
    await cb.answer()

# ── возврат в меню ─────────────────────────────────────────────────────
@router.callback_query(lambda c: c.data == f"{CALLBACK_PREFIX}_tests_go_back")
async def tests_go_back(cb: CallbackQuery):
    await cb.message.answer("Выбери номер ОГЭ-теста:", reply_markup=get_tests_types_kb(with_menu=True, include_back=True))
    await cb.answer()

# =========================
# Кнопка возврата в главное меню
# =========================
@router.callback_query(lambda c: c.data == "to_main_menu")
async def to_main_menu(cb: CallbackQuery):
    await cb.message.answer("Главное меню:", reply_markup=main_kb)
    await cb.answer()

# ======================================================================
#       НОВЫЙ ФУНКЦИОНАЛ: РАБОТА НАД ОШИБКАМИ (с кнопками)
# ======================================================================

# --- Кнопка "Работа над ошибками" ---
@router.callback_query(lambda c: c.data == f"{CALLBACK_PREFIX}_work_on_mistakes")
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
            [InlineKeyboardButton(text=f"Тест {t}", callback_data=f"{CALLBACK_PREFIX}_mistake_test_{t}")]
            for t in mistake_tests
        ] + [
            [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="to_main_menu")]
        ]
    )
    await cb.message.answer("Выбери тест, где были ошибки:", reply_markup=kb)
    await cb.answer()

# --- Старт работы над ошибками по выбранному тесту ---
@router.callback_query(lambda c: c.data.startswith(f"{CALLBACK_PREFIX}_mistake_test_"))
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
    user_test_state_oge[user_id] = {
        "type": test_type,
        "idx": 0,
        "mistake_q_ids": mistake_q_ids_unique
    }
    await send_next_mistake_question(user_id, cb.message)
    await cb.answer()

# --- Отправка следующего ошибочного вопроса ---
async def send_next_mistake_question(user_id, message_obj):
    state = user_test_state_oge.get(user_id)
    idx = state["idx"]
    q_ids = state["mistake_q_ids"]
    if idx >= len(q_ids):
        user_test_state_oge.pop(user_id, None)
        await message_obj.answer("Все ошибки в этом тесте исправлены! 👍")
        return
    q_id = q_ids[idx]
    q = get_question_by_id(q_id)
    log_question_started(user_id, _t(state["type"]), q_id)  # --- ЛОГИРОВАНИЕ СТАРТА ---
    options = q['options'].split('\n')
    formatted_q = _format_question_text(q['question'])
    msg = (
        f"Ошибка {idx+1} из {len(q_ids)} (ОГЭ. Тест {state['type']})\n\n"
        f"{formatted_q}\n\n" +
        "\n".join([f"{i+1}. {opt}" for i, opt in enumerate(options)]) +
        "\n\nПовтори попытку: введи номер(а) ответа:"
    )
    used_hints = user_test_state_oge.get(user_id, {}).get("used_hints", {}).get(state["type"], 0)
    hints_left = max(0, 10 - used_hints)
    kb = get_stop_test_kb(q_id, hints_left=hints_left)
    sent_q = await message_obj.answer(_to_html_with_code(msg), parse_mode="HTML", reply_markup=kb)
    user_test_state_oge[user_id]["last_question_msg_id"] = sent_q.message_id

# --- Проверка ответа пользователя на ошибочный вопрос ---
@router.message(lambda m: (
    m.from_user.id in user_test_state_oge
    and "mistake_q_ids" in user_test_state_oge[m.from_user.id]
    and isinstance(getattr(m, "text", None), str)
    and any(ch.isdigit() for ch in m.text)
))
async def check_mistake_answer(m: types.Message):
    state = user_test_state_oge.get(m.from_user.id)
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
        user_test_state_oge[m.from_user.id]["idx"] += 1
    else:
        log_question_answered(m.from_user.id, q_id, m.text, False)  # --- ЛОГИРОВАНИЕ ОТВЕТА ---
        # Удаляем текущий id из очереди, чтобы не повторялся подряд; вернём в конец, если ещё неверно
        try:
            state["mistake_q_ids"].pop(idx)
        except (ValueError, IndexError) as e:
            log_error(f"Data error popping mistake_q_ids at index {idx} for user {m.from_user.id}: {e}")
        except Exception as e:
            log_error(f"Unexpected error popping mistake_q_ids at index {idx} for user {m.from_user.id}: {e}")
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
    user_test_state_oge[m.from_user.id]["last_result_msg_id"] = sent.message_id
    # Переход к следующему вопросу ошибок — только после «Далее»
    # Обновим сетку статусов, если она показана в чате
    try:
        grid_msg_id = user_test_state_oge.get(m.from_user.id, {}).get("grid_msg_id")
        if grid_msg_id:
            test_type = user_test_state_oge[m.from_user.id]["type"]
            # В режиме ошибок глобального списка q_ids может не быть — пропустим
            q_ids = user_test_state_oge[m.from_user.id].get("q_ids")
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
                        log_error(e, f"Error updating grid markup in mistake mode for user {m.from_user.id}")
    except Exception as e:
        log_error(e, f"Error updating grid in check_mistake_answer for user {m.from_user.id}")
