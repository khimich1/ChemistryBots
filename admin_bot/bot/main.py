import asyncio
import logging
import os
from datetime import datetime
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv

from .handlers import menu
from .services.db import Database, set_default_db


async def main() -> None:
    # Создаём папку для логов
    os.makedirs("logs", exist_ok=True)
    
    # Настраиваем логирование в файл
    log_filename = f"logs/bot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_filename, encoding='utf-8'),
            logging.StreamHandler()  # Также выводим в консоль
        ]
    )
    
    load_dotenv()

    bot_token = os.getenv("BOT_TOKEN")
    if not bot_token or bot_token == "PUT_YOUR_TOKEN_HERE":
        raise RuntimeError("BOT_TOKEN is not set. Please edit .env and re-run.")

    users_db_path = os.getenv("USERS_DB_PATH")
    if not users_db_path:
        raise RuntimeError("USERS_DB_PATH is not set in .env file")

    db = Database(users_db_path)
    db.ensure_teacher_table()
    set_default_db(db)

    bot = Bot(token=bot_token, parse_mode=ParseMode.HTML)
    dp = Dispatcher(storage=MemoryStorage())

    dp.include_router(menu.router)

    logger = logging.getLogger(__name__)
    logger.info("Starting Admin_bot polling...")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
