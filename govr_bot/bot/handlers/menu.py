from aiogram import Router, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

from bot.utils import user_learning_state
from bot.services.spreadsheet import fetch_user_records
from bot.services.answer_db import get_user_full_name, set_user_full_name
from bot.services.pdf_generator import make_report
from bot.services.notes_ocr import recognize_notes_from_image
from io import BytesIO

# если main_kb используется в других файлах — импортируй там: from bot.handlers.menu import main_kb

router = Router()
class ProfileStates(StatesGroup):
    waiting_full_name = State()

class OcrStates(StatesGroup):
    waiting_photo = State()

# ==== Главное меню (обновлено) ====
main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="📚 Теория по химии"),
            KeyboardButton(text="📝 Тесты"),
        ],
        [
            KeyboardButton(text="📸 Распознать конспект"),
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
        "• 📸 Распознать конспект — пришли фото, верну аккуратный текст\n"
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
        "- 📸 Распознать конспект — пришли фото, верну аккуратный текст\n"
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
        "3) Кнопки: «💡 Подсказка», «⏹️ Стоп тест».\n"
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

# ==== Распознать конспект ====
@router.message(lambda m: m.text == "📸 Распознать конспект")
async def ask_for_notes_photo(m: types.Message, state: FSMContext):
    await state.set_state(OcrStates.waiting_photo)
    await m.answer(
        "📸 Распознать конспект\n\n"
        "Сделайте фото страницы или пришлите снимок из галереи.\n"
        "После распознавания пришлю аккуратно оформленный текст.\n\n"
        "Чтобы выйти — нажмите «⬅️ В меню»."
    )


@router.message(OcrStates.waiting_photo)
async def handle_notes_photo(m: types.Message, state: FSMContext):
    # Возможность выйти в меню
    if (m.text or "").lower().strip() in {"⬅️ в меню", "в меню", "/menu"}:
        await state.clear()
        await m.answer("Возвращаю в меню.", reply_markup=main_kb)
        return

    if not getattr(m, "photo", None):
        await m.answer("Пожалуйста, пришлите фото конспекта 📷")
        return

    await m.answer("🔎 Распознаю фото… Подождите пару секунд")
    try:
        # Берём самое большое превью и скачиваем через встроенный клиент aiogram (без логгирования URL с токеном)
        file = await m.bot.get_file(m.photo[-1].file_id)
        buffer = BytesIO()
        await m.bot.download(file, destination=buffer)
        img_bytes = buffer.getvalue()

        text = await recognize_notes_from_image(img_bytes)
        if not text:
            await m.answer("Не удалось распознать текст на фото. Попробуйте сделать снимок чётче и без бликов.")
        else:
            await m.answer(text)
    except Exception:
        await m.answer("Произошла ошибка при распознавании. Попробуйте ещё раз позже.")
    finally:
        await state.clear()
