from aiogram import Router, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

from bot.utils import user_learning_state
from bot.services.spreadsheet import fetch_user_records
from bot.services.answer_db import get_user_full_name, set_user_full_name
from bot.services.pdf_generator import make_report
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
    ],
    resize_keyboard=True
)

# ==== /start и возврат в меню ====
@router.message(lambda m: (m.text or "").lower() in {"/start", "меню"} or ("в главное меню" in (m.text or "").lower()))
async def cmd_start(m: types.Message, state: FSMContext):
    full_name = get_user_full_name(m.from_user.id)
    if not full_name:
        await state.set_state(ProfileStates.waiting_full_name)
        await m.answer(
            "Пожалуйста, напиши своё имя и фамилию в одном сообщении (например: Иван Петров).\n"
            "Это нужно для отчётов и статистики.")
        return

    await m.answer(
        "👋 Привет! Я помогу тебе разобраться в химии.\n\n"
        "• 📚 Теория по химии — изучай главы по разделам (Начала, Элементы, Органика)\n"
        "• 🔬 Решатор задач — пришли текст или фото задачи\n"
        "• 📝 Тесты — тренируйся и работай над ошибками\n"
        "• 📈 Получить отчёт — PDF с твоим прогрессом",
        reply_markup=main_kb
    )

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
    await m.answer(
        "Спасибо! Сохранил твоё имя. Ниже — главное меню.",
        reply_markup=main_kb
    )

# ==== Подменю «Теория по химии» ====
@router.message(lambda m: m.text == "📚 Теория по химии")
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

# ==== Отчёт (PDF) ====
@router.message(lambda m: m.text == "📈 Получить отчёт")
async def get_report(m: types.Message):
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
        except Exception as e:
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
