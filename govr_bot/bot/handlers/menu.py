from aiogram import Router, types
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile

from bot.utils import user_learning_state
from bot.services.spreadsheet import fetch_user_records
from bot.services.pdf_generator import make_report

# если main_kb используется в других файлах — импортируй там: from bot.handlers.menu import main_kb

router = Router()

# ==== Главное меню (обновлено) ====
main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="📚 Теория по химии"),
            KeyboardButton(text="📝 Тесты"),
        ],
        [
            KeyboardButton(text="🧪 Устный зачет"),
            KeyboardButton(text="📈 Получить отчёт"),
        ],
        [
            KeyboardButton(text="ℹ️ Как работает бот"),
        ],
    ],
    resize_keyboard=True
)

# ==== /start и возврат в меню ====
@router.message(lambda m: m.text == "/start" or m.text == "Меню" or m.text == "⬅️ В меню")
async def cmd_start(m: types.Message):
    await m.answer(
        "👋 Привет! Я помогу тебе разобраться в химии.\n\n"
        "• 📚 Теория по химии — изучай главы по разделам (Начала, Элементы, Органика)\n"
        "• 🧪 Устный зачет — отвечай голосом, ИИ проверит и подскажет\n"
        "• 📝 Тесты — тренируйся и работай над ошибками\n"
        "• 📈 Получить отчёт — PDF с твоим прогрессом",
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
    await m.answer(
        "ℹ️ Как пользоваться ботом:\n"
        "1) Зайди в «📚 Теория по химии», выбери раздел и главу\n"
        "2) Читай порции теории, задавай вопросы («❓ Есть вопрос»)\n"
        "3) Проходи «📝 Тесты», а затем «Работа над ошибками»\n"
        "4) Забирай «📈 Отчёт» с прогрессом\n\n"
        "Вернуться в это меню можно кнопкой «⬅️ В меню».",
        reply_markup=main_kb
    )

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
