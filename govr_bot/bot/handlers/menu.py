from aiogram import Router, types
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
)
from bot.utils import LEARNING_TOPICS, user_learning_state
from bot.services.spreadsheet import fetch_user_records
from bot.services.pdf_generator import make_report

# если main_kb используется в других файлах — импортируй там: from bot.handlers.menu import main_kb

router = Router()

# Главное меню
main_kb = types.ReplyKeyboardMarkup(
    keyboard=[
        [
            types.KeyboardButton(text="🌱 Курс по органике"),
            types.KeyboardButton(text="📝 Тесты")
        ],
        [
            types.KeyboardButton(text="🧪 Устный зачет"),
            types.KeyboardButton(text="📈 Получить отчёт"),
        ],
        [
 #           types.KeyboardButton(text="▶️ Продолжить"),
            types.KeyboardButton(text="ℹ️ Как работает бот")
            
        ]
    ],
    resize_keyboard=True
)   # <-- Скобка!


@router.message(lambda m: m.text == "/start" or m.text == "Меню")
async def cmd_start(m: types.Message):
    await m.answer(
        "👋 Добро пожаловать! Я помогу тебе разобраться в органической химии.\n\n"
        "• 🌱 Курс по органике — изучи весь курс по органической химии по главам.\n"
        "• ▶️ Продолжить — возобновить курс.\n"
        "• 📊 Получить отчёт — PDF с прогрессом.\n"
        "• 🧪 Устный зачет — усный зачет по всем темам с проверкой ИИ.\n"
        "• 📝 Тесты — пройти готовые тесты.",
        reply_markup=main_kb
)

@router.message(lambda m: m.text == "🌱 Курс по органике")
async def on_learning_start(m: types.Message):
    # Показываем список глав курса как inline-кнопки
    buttons = [
        [InlineKeyboardButton(text=topic, callback_data=f"learn_topic_{i}")]
        for i, topic in enumerate(LEARNING_TOPICS)
    ]
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await m.answer(
        "🌱 Добро пожаловать на курс по органической химии!\n\n"
        "Здесь ты можешь проходить главы, изучать теорию и выполнять задания.\n"
        "Чтобы начать — выбери тему из списка ниже.",
        reply_markup=kb
    )

@router.message(lambda m: m.text == "📈 Получить отчёт")
async def get_report(m: types.Message):
    records = fetch_user_records(m.from_user.id)
    if not records:
        return await m.answer("Ты ещё не сдал ни одной темы.")
    pdf_path = make_report(m.from_user.id, m.from_user.full_name, records)
    await m.answer_document(FSInputFile(pdf_path), caption="Вот твой PDF-отчёт!")

@router.message(lambda m: m.text == "ℹ️ Как работает бот")
async def how_bot_works(m: types.Message):
    await m.answer(
        "ℹ️ Я — учебный бот по органической химии:\n"
        "1. Выбирай темы или проходи курс по главам\n"
        "2. Отвечай на вопросы (текстом или голосом)\n"
        "3. Получай обратную связь и рекомендации\n"
        "4. Выполняй тесты, следи за прогрессом!\n"
        "Можно возвращаться в меню через кнопку Меню."
    )

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

# Можно добавить любые дополнительные обработчики кнопок и сообщений