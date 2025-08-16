import asyncio
import logging
import os
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from dotenv import load_dotenv

load_dotenv()

# Токен читаем из BOT_TOKEN (как в других ботах)
PARENT_BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

logging.basicConfig(level=logging.INFO)
from bot.handlers.menu import router as menu_router


async def set_bot_commands(bot: Bot):
    commands = [
        BotCommand(command="start", description="Начать"),
        BotCommand(command="menu", description="Меню"),
    ]
    await bot.set_my_commands(commands)


async def main():
    bot = Bot(token=PARENT_BOT_TOKEN, parse_mode="HTML")
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(menu_router)

    await set_bot_commands(bot)
    logging.info("Parent bot started!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())


