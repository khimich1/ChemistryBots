import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand
from aiogram.fsm.storage.memory import MemoryStorage
from bot.services.answer_db import init_db, init_progress_table
init_db()
init_progress_table() 
from bot.handlers.menu import router as menu_router
from bot.handlers.topics import router as topics_router
from bot.handlers.tests import router as tests_router
from bot.handlers.report import router as report_router

# --- Конфиг и токен ---
from dotenv import load_dotenv
import os

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")  # токен из .env

# --- Настройка логирования ---
logging.basicConfig(level=logging.INFO)

async def set_bot_commands(bot: Bot):
    commands = [
        BotCommand(command="start", description="Начать работу с ботом"),
        BotCommand(command="menu", description="Главное меню"),
        BotCommand(command="help", description="Как работает бот"),
        BotCommand(command="report", description="Получить отчёт"),
        BotCommand(command="resume", description="Продолжить курс"),
        BotCommand(command="tests", description="Пройти тесты"),
    ]
    await bot.set_my_commands(commands)

async def main():
    # --- Инициализация бота и диспетчера ---
    bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
    dp = Dispatcher(storage=MemoryStorage())

    # --- Подключение роутеров ---
    dp.include_router(menu_router)
    dp.include_router(tests_router)     # tests ДО topics!
    dp.include_router(topics_router)
    dp.include_router(report_router)

    # --- Установка команд ---
    await set_bot_commands(bot)

    # --- Запуск polling ---
    print("Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
