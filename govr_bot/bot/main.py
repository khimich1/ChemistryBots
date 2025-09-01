import asyncio
import logging
import time
import signal
import sys
from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import TelegramNetworkError, TelegramAPIError
from bot.services.answer_db import init_db, init_progress_table, close_all_connections
init_db()
init_progress_table() 
from bot.handlers.menu import router as menu_router
from bot.handlers.topics import router as topics_router
from bot.handlers.tests import router as tests_router
from bot.handlers import tests_oge

from bot.handlers.flashcards import router as flashcards_router
from bot.handlers.billing import router as billing_router
from bot.services.plan import init_billing_tables
from bot.handlers.admin import router as admin_router

# --- Конфиг и токен ---
from dotenv import load_dotenv
import os

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")  # токен из .env

# --- Настройка логирования ---
from bot.utils_pkg_new.logger import setup_logging, log_error
setup_logging()

# Импорт rate limiter
from bot.utils_pkg_new.rate_limiter import cleanup_rate_limiters

# Глобальные переменные для graceful shutdown
bot_instance = None
dp_instance = None
cleanup_task = None

def signal_handler(signum, frame):
    """Обработчик сигналов для graceful shutdown"""
    print(f"\nПолучен сигнал {signum}. Завершаем работу бота...")
    if bot_instance:
        asyncio.create_task(shutdown_bot())
    sys.exit(0)

async def shutdown_bot():
    """Graceful shutdown бота"""
    global bot_instance, dp_instance, cleanup_task
    try:
        if cleanup_task:
            cleanup_task.cancel()
        if dp_instance:
            await dp_instance.stop_polling()
        if bot_instance:
            await bot_instance.session.close()
        close_all_connections()
        print("Бот успешно остановлен")
    except Exception as e:
        log_error(e, "Error during bot shutdown")

# Регистрируем обработчики сигналов
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

async def set_bot_commands(bot: Bot):
    """Устанавливает команды бота с повторными попытками при сетевых ошибках"""
    commands = [
        BotCommand(command="start", description="Начать работу с ботом"),
        BotCommand(command="menu", description="Главное меню"),
        BotCommand(command="help", description="Как работает бот"),
        BotCommand(command="report", description="Получить отчёт"),
        BotCommand(command="resume", description="Продолжить курс"),
        BotCommand(command="tests", description="Пройти тесты"),
        BotCommand(command="stats", description="📊 Статистика бота (админ)"),
        BotCommand(command="stats_clean", description="📊 Статистика без админов (админ)"),
        BotCommand(command="help_admin", description="🛠️ Справка по админским командам"),
        BotCommand(command="retention_week", description="📈 Удержание за неделю (админ)"),
    ]
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            await bot.set_my_commands(commands)
            break
        except TelegramNetworkError as e:
            if attempt < max_retries - 1:
                log_error(e, f"Network error setting commands (attempt {attempt + 1})")
                await asyncio.sleep(2 ** attempt)  # Экспоненциальная задержка
            else:
                log_error(e, "Failed to set bot commands after all retries")
        except Exception as e:
            log_error(e, "Unexpected error setting bot commands")
            break

async def main():
    """Основная функция с улучшенной обработкой ошибок и поддержкой высокой нагрузки"""
    global bot_instance, dp_instance, cleanup_task
    
    # --- Инициализация бота и диспетчера ---
    bot_instance = Bot(token=BOT_TOKEN, parse_mode="HTML")
    dp_instance = Dispatcher(storage=MemoryStorage())
    
    # Инициализация таблиц тарифов/использования
    try:
        init_billing_tables()
    except Exception as e:
        logging.warning(f"Billing tables init failed: {e}")
    
    # Подключаем middleware подписки
    try:
        from bot.middlewares.subscription_gate import SubscriptionGateMiddleware
        dp_instance.message.middleware(SubscriptionGateMiddleware(enabled=True))
        dp_instance.callback_query.middleware(SubscriptionGateMiddleware(enabled=True))
    except Exception as e:
        logging.warning(f"Subscription middleware not enabled: {e}")

    # --- Подключение роутеров ---
    dp_instance.include_router(menu_router)
    dp_instance.include_router(billing_router)   # billing ДО tests и topics!
    dp_instance.include_router(topics_router)    # topics ПЕРЕД tests!
    dp_instance.include_router(tests_router)     # tests ПОСЛЕ topics!
    dp_instance.include_router(tests_oge.router) # ОГЭ тесты
    dp_instance.include_router(flashcards_router)
    dp_instance.include_router(admin_router)     # Админские команды

    # --- Установка команд ---
    await set_bot_commands(bot_instance)

    # --- Запуск rate limiter cleanup ---
    cleanup_task = asyncio.create_task(cleanup_rate_limiters())

    # --- Запуск polling с повторными попытками ---
    print("🚀 Бот запущен! Готов к работе с высокой нагрузкой!")
    print("📊 Ожидаемая нагрузка: 150-200 пользователей одновременно")
    print("🛡️ Rate limiting включен для защиты от спама")
    
    max_retries = 5
    retry_delay = 5
    
    while True:
        try:
            await dp_instance.start_polling(bot_instance, polling_timeout=30)
        except TelegramNetworkError as e:
            log_error(e, "Network error during polling, retrying...")
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 60)  # Увеличиваем задержку, но не более 60 сек
        except TelegramAPIError as e:
            log_error(e, "Telegram API error during polling, retrying...")
            await asyncio.sleep(retry_delay)
        except KeyboardInterrupt:
            print("\nБот остановлен пользователем")
            break
        except Exception as e:
            log_error(e, "Unexpected error during polling")
            await asyncio.sleep(retry_delay)
        finally:
            try:
                await bot_instance.session.close()
            except Exception as e:
                log_error(e, "Error closing bot session")

if __name__ == "__main__":
    asyncio.run(main())
