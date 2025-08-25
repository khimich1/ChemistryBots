from aiogram import Router, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

from bot.utils import user_learning_state
from bot.services.spreadsheet import fetch_user_records
from bot.services.answer_db import (
    get_user_full_name,
    set_user_full_name,
    get_random_motivation_text,
    get_user_activity_stats,
    log_start_param,
    mark_subscribed,
)
from bot.services.pdf_generator import make_report
from bot.services.subscription import is_user_subscribed, build_subscribe_kb
from bot.services.task_solver import process_image_for_task_or_conspect, solve_text_task, is_chemistry_task
from io import BytesIO

# если main_kb используется в других файлах — импортируй там: from bot.handlers.menu import main_kb

router = Router()
class ProfileStates(StatesGroup):
    waiting_full_name = State()

class TaskSolverStates(StatesGroup):
    waiting_photo = State()

# ==== Главное меню (обновлено) ====
main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="📚 Теория по химии"),
            KeyboardButton(text="📝 Тесты"),
        ],
        [
            KeyboardButton(text="🔬 Решатор задач"),
            KeyboardButton(text="📈 Получить отчёт"),
        ],
        [
            KeyboardButton(text="🃏 Карточки для запоминания"),
            KeyboardButton(text="ℹ️ Как работает бот"),
        ],
        [
            KeyboardButton(text="💳 Тарифы и оплата"),
            KeyboardButton(text="📞 Бесплатное занятие"),
        ],
    ],
    resize_keyboard=True
)

# ==== /start и возврат в меню ====
@router.message(lambda m: (
    (m.text or "").strip().lower() in {"/start", "/menu", "меню", "в меню", "в главное меню", "⬅️ в меню"}
    or ("меню" in (m.text or "").lower())
))
async def cmd_start(m: types.Message, state: FSMContext):
    # Логируем метку источника из /start <param>
    try:
        text = (m.text or "").strip()
        parts = text.split(maxsplit=1)
        start_param = parts[1] if len(parts) == 2 and parts[0].lower().startswith("/start") else None
        log_start_param(m.from_user.id, getattr(m.from_user, "username", None), start_param)
    except Exception:
        pass
    # Сначала проверим подписку. Если нет — предложим подписаться и прервёмся.
    if not await is_user_subscribed(m.bot, m.from_user.id):
        await m.answer(
            "Чтобы пользоваться ботом, подпишись на канал и нажми 'Проверить подписку'.",
            reply_markup=build_subscribe_kb(),
        )
        return
    full_name = get_user_full_name(m.from_user.id)
    if not full_name:
        await state.set_state(ProfileStates.waiting_full_name)
        await m.answer(
            "Пожалуйста, напиши своё имя и фамилию в одном сообщении (например: Иван Петров).\n"
            "Это нужно для отчётов и статистики.")
        return

    # Отправим мотивационное сообщение (если таблица chem_motivation есть в базе)
    mot = get_random_motivation_text()
    if mot:
        try:
            await m.answer(mot)
        except Exception:
            pass

    # Мотивация и статистика активности
    streak, last7 = get_user_activity_stats(m.from_user.id)
    mot = get_random_motivation_text()
    extra_lines: list[str] = []
    if streak and streak > 1:
        extra_lines.append(f"Ты шёл к своей цели {streak} дн. подряд. Не останавливайся!")
    if last7:
        extra_lines.append(f"Активных дней за 7 дней: {last7}.")
    if mot:
        extra_lines.append(mot)

    await m.answer(
        "👋 Привет! Я помогу тебе разобраться в химии.\n\n"
        "• 📚 Теория по химии — изучай главы по разделам (Начала, Элементы, Органика)\n"
        "• 🔬 Решатор задач — пришли текст или фото задачи\n"
        "• 📝 Тесты — тренируйся и работай над ошибками\n"
        "• 📈 Получить отчёт — PDF с твоим прогрессом"
        + ("\n\n" + "\n".join(extra_lines) if extra_lines else ""),
        reply_markup=main_kb
    )

@router.callback_query(lambda c: c.data == "check_sub")
async def on_check_subscription(cb: types.CallbackQuery, state: FSMContext):
    # Повторная проверка подписки по кнопке
    if await is_user_subscribed(cb.bot, cb.from_user.id):
        try:
            mark_subscribed(cb.from_user.id)
        except Exception:
            pass
        # Удалим сообщение с кнопками, если возможно
        try:
            await cb.message.delete()
        except Exception:
            pass

        full_name = get_user_full_name(cb.from_user.id)
        if not full_name:
            await state.set_state(ProfileStates.waiting_full_name)
            await cb.message.answer(
                "Пожалуйста, напиши своё имя и фамилию в одном сообщении (например: Иван Петров).\n"
                "Это нужно для отчётов и статистики."
            )
        else:
            await cb.message.answer("Спасибо за подписку! Ниже — главное меню.", reply_markup=main_kb)
        await cb.answer("Подписка подтверждена ✅", show_alert=False)
    else:
        await cb.answer("Ещё не вижу подписки. Подпишись и попробуй снова.", show_alert=True)
        try:
            await cb.message.answer(
                "Подписка всё ещё не подтверждена. Нажми ещё раз 'Проверить подписку' после подписки.",
                reply_markup=build_subscribe_kb(),
            )
        except Exception:
            pass

@router.message(ProfileStates.waiting_full_name)
async def set_full_name(m: types.Message, state: FSMContext):
    text = (m.text or "").strip()
    # Простая валидация: хотя бы два слова
    parts = [p for p in text.replace("  ", " ").split(" ") if p]
    if len(parts) < 2:
        await m.answer("Похоже, это не имя и фамилия. Напиши, пожалуйста, имя и фамилию, например: Мария Иванова")
        return
    full_name = " ".join(parts[:3])  # на всякий — первые 2-3 слова
    set_user_full_name(m.from_user.id, getattr(m.from_user, "username", None), full_name)
    await state.clear()
    # Возврат в меню с мотивацией
    mot = get_random_motivation_text()
    if mot:
        try:
            await m.answer(mot)
        except Exception:
            pass

    await m.answer("Ниже — главное меню.", reply_markup=main_kb)

# ==== Подменю «Теория по химии» ====
@router.message(lambda m: (m.text or "").strip().lower() in {
    "📚 теория по химии",
    "курс по химии",
    "курс",
    "теория",
})
async def theory_menu(m: types.Message):
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📖 Начала химии")],
            [KeyboardButton(text="⚗️ Химия элементов")],
            [KeyboardButton(text="🧬 Органическая химия")],
            [KeyboardButton(text="⬅️ В меню")],
        ],
        resize_keyboard=True
    )
    await m.answer("Выбери раздел теории:", reply_markup=kb)

# ==== Подменю «Тесты» из главного меню ====
@router.message(lambda m: (m.text or "").strip().lower() == "📝 тесты")
async def tests_entry_menu(m: types.Message):
    # Завершаем активную сессию теории, если была
    try:
        from bot.handlers.topics import user_learning_state
        user_learning_state.pop(m.from_user.id, None)
    except Exception:
        pass
    from bot.handlers.tests import tests_instruction_text
    await m.answer(tests_instruction_text(), parse_mode="HTML")
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🧪 Тестовая часть ЕГЭ по химии")],
            [KeyboardButton(text="⬅️ В меню")],
        ],
        resize_keyboard=True
    )
    await m.answer("Раздел тестов:", reply_markup=kb)

@router.message(lambda m: (m.text or "").strip().lower() == "🧪 тестовая часть егэ по химии")
async def tests_open_catalog(m: types.Message):
    # На всякий случай тоже завершим теорию
    try:
        from bot.handlers.topics import user_learning_state
        user_learning_state.pop(m.from_user.id, None)
    except Exception:
        pass
    from bot.handlers.tests import get_tests_types_kb
    kb = get_tests_types_kb(with_menu=True, include_back=True)
    await m.answer("Выбери тест:", reply_markup=kb)

@router.callback_query(lambda c: c.data == "tests_go_back")
async def tests_go_back(cb: types.CallbackQuery):
    # Удаляем сообщение со списком тестов
    try:
        await cb.message.delete()
    except Exception:
        # если не удалилось — просто продолжим и перешлём меню ниже
        pass
    # Возврат к подменю тестов (кнопки Reply)
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🧪 Тестовая часть ЕГЭ по химии")],
            [KeyboardButton(text="⬅️ В меню")],
        ],
        resize_keyboard=True
    )
    await cb.message.answer("Раздел тестов:", reply_markup=kb)
    await cb.answer()

# Универсальная кнопка «В главное меню» для инлайн-кнопок
@router.callback_query(lambda c: c.data == "to_main_menu")
async def to_main_menu_cb(cb: types.CallbackQuery):
    # Удаляем последнее сообщение и ещё 4 предыдущих (всего до 5)
    try:
        base = cb.message.message_id
        for delta in range(0, 5):
            try:
                await cb.message.bot.delete_message(chat_id=cb.message.chat.id, message_id=base - delta)
            except Exception:
                pass
    except Exception:
        pass
    await cb.message.answer("Главное меню:", reply_markup=main_kb)
    await cb.answer()

# ==== Отчёт (PDF) ====
@router.message(lambda m: m.text == "📈 Получить отчёт")
async def get_report(m: types.Message):
    # Лимит 1 PDF/месяц для бесплатного тарифа
    try:
        from bot.services.plan import get_user_plan_code, limits_for, consume_monthly
        plan = get_user_plan_code(m.from_user.id)
        limit = limits_for(plan)["reports_per_month"]
        ok, _left = consume_monthly(m.from_user.id, "report", limit)
        if not ok:
            await m.answer("В бесплатном тарифе — 1 PDF-отчёт в месяц. Оформи подписку в ‘💳 Тарифы и оплата’.")
            return
    except Exception:
        pass

    records = fetch_user_records(m.from_user.id)
    if not records:
        await m.answer("Пока нет данных для отчёта — пройди темы или тесты.")
        return
    pdf_path = make_report(m.from_user.id, m.from_user.full_name, records)
    await m.answer_document(FSInputFile(pdf_path), caption="Вот твой PDF-отчёт!")

# ==== Справка ====
@router.message(lambda m: m.text == "ℹ️ Как работает бот")
async def how_bot_works(m: types.Message):
    text = (
        "ℹ️ Памятка: как пользоваться ботом\n\n"
        "Главное меню:\n"
        "- 📚 Теория по химии — учим главы\n"
        "- 📝 Тесты — тренировка по вариантам\n"
        "- 🔬 Решатор задач — пришли текст или фото задачи\n"
        "- 📈 Получить отчёт — PDF с прогрессом\n\n"
        "Теория (раздел «📚 Теория по химии»):\n"
        "1) Выбери: «📖 Начала химии», «⚗️ Химия элементов», «🧬 Органическая химия».\n"
        "2) Нажми на главу. Рядом цветной индикатор прогресса: 🟩/🟨/🟥/⬛.\n"
        "3) Внутри главы есть кнопки:\n"
        "   • Далее/◀️ Назад — листать порции\n"
        "   • 🔊 Слушать аудио — если доступно\n"
        "   • ❓ Спросить ИИ — задать свой вопрос\n"
        "   • 📝 Задание — вопрос по текущему фрагменту\n"
        "   • ■ Стоп — выйти из главы\n"
        "   • 🏠 К главам — вернуться к списку\n\n"
        "Задание:\n"
        "- Отправь ответ текстом или голосом.\n"
        "- Если не получилось — кнопка «🔁 Другой вопрос».\n"
        "- При неверном ответе появится «💡 Показать образец ответа».\n"
        "- При верном ответе увидишь статистику по теме и кнопки «🔄 Ещё вопрос» или «➡️ К следующему разделу».\n\n"
        "Тесты (кнопка «📝 Тесты»):\n"
        "1) Выбери номер теста.\n"
        "2) Отвечай цифрами (например: 2 или 13).\n"
        "3) Кнопки: «💡 Подсказка», «⏹️ Стоп тест», «❗ Пожаловаться».\n"
        "4) Прерванный тест можно продолжить — бот предложит «▶️ Продолжить» или «🔄 Начать заново».\n"
        "5) «💡 Работа над ошибками» — повтор только неверных вопросов.\n\n"
        "Полезные команды:\n"
        "/start — начать\n"
        "/menu — главное меню\n"
        "/help — эта справка\n"
        "/report — PDF-отчёт\n"
        "/resume — продолжить последнюю главу\n"
        "/tests — открыть меню тестов\n\n"
        "Если что-то запуталось — нажми «⬅️ В меню» или «Стоп тест»."
    )
    await m.answer(text, reply_markup=main_kb)

# Дублируем справку на команду /help
@router.message(Command("help"))
async def help_cmd(m: types.Message):
    await how_bot_works(m)

# ==== (опционально) Возобновление курса, если где-то используется ====
@router.message(lambda m: m.text == "▶️ Продолжить")
async def resume_course(m: types.Message):
    state = user_learning_state.get(m.from_user.id)
    if not state:
        await m.answer("Ты ещё не начинал обучение. Открой «📚 Теория по химии» и выбери раздел.", reply_markup=main_kb)
        return
    # Если состояние есть — показываем следующий chunk
    from bot.handlers.topics import send_next_chunk
    await send_next_chunk(m.from_user.id, m.bot)

# ==== Решатор задач ====
@router.message(lambda m: m.text == "🔬 Решатор задач")
async def ask_for_task_or_conspect_photo(m: types.Message, state: FSMContext):
    await state.set_state(TaskSolverStates.waiting_photo)
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="⬅️ В меню")]],
        resize_keyboard=True
    )
    
    await m.answer(
        "🔬 Решатор задач\n\n"
        "Отправьте:\n"
        "• 📝 Текст химической задачи — получите решение с объяснениями\n"
        "• 📸 Фото химической задачи — получите решение с объяснениями\n"
        "• 📸 Фото конспекта — получите аккуратно оформленный текст\n\n"
        "⚠️ Важно: в заданиях и конспектах категорически нельзя ничего менять или добавлять!\n\n"
        "Чтобы выйти — нажмите кнопку «⬅️ В меню» внизу.",
        reply_markup=kb
    )


@router.message(TaskSolverStates.waiting_photo)
async def handle_task_or_conspect_input(m: types.Message, state: FSMContext):
    # Возможность выйти в меню
    if (m.text or "").lower().strip() in {"⬅️ в меню", "в меню", "/menu"}:
        await state.clear()
        await m.answer("Возвращаю в меню.", reply_markup=main_kb)
        return

    # Обработка текстового сообщения
    if m.text:
        await m.answer("🔎 Анализирую текст… Подождите пару секунд")
        try:
            # Проверяем, является ли текст химической задачей
            is_task = await is_chemistry_task(m.text)

            if is_task:
                solution = await solve_text_task(m.text)
                if solution:
                    await m.answer("📝 Решение задачи:\n\n" + solution)
                else:
                    await m.answer("Не удалось решить задачу. Попробуйте сформулировать её более чётко.")
            else:
                await m.answer(
                    "🔍 Это не похоже на химическую задачу.\n\n"
                    "Отправьте:\n"
                    "• 📝 Текст химической задачи — получите решение с объяснениями\n"
                    "• 📸 Фото химической задачи — получите решение с объяснениями\n"
                    "• 📸 Фото конспекта — получите аккуратно оформленный текст\n\n"
                    "⚠️ Важно: в заданиях и конспектах категорически нельзя ничего менять или добавлять!"
                )
        except Exception:
            await m.answer("Произошла ошибка при обработке текста. Попробуйте ещё раз позже.")
        finally:
            await state.clear()
        return

    # Обработка фото
    if getattr(m, "photo", None):
        await m.answer("🔎 Анализирую фото… Подождите пару секунд")
        try:
            # Берём самое большое превью и скачиваем через встроенный клиент aiogram
            file = await m.bot.get_file(m.photo[-1].file_id)
            buffer = BytesIO()
            await m.bot.download(file, destination=buffer)
            img_bytes = buffer.getvalue()

            content_type, result = await process_image_for_task_or_conspect(img_bytes)
            
            if content_type == "НЕ_ОПРЕДЕЛЕНО":
                await m.answer(result)
            elif not result:
                await m.answer("Не удалось обработать фото. Попробуйте сделать снимок чётче и без бликов.")
            else:
                # Добавляем заголовок в зависимости от типа контента
                if content_type == "ЗАДАЧА":
                    header = "📝 Решение задачи:\n\n"
                else:  # КОНСПЕКТ
                    header = "📸 Распознанный конспект:\n\n"
                
                await m.answer(header + result)
        except Exception as e:
            await m.answer("Произошла ошибка при обработке фото. Попробуйте ещё раз позже.")
        finally:
            await state.clear()
        return

    # Если отправлено что-то другое
    await m.answer("Пожалуйста, отправьте текст химической задачи или фото задачи/конспекта 📝📷")
