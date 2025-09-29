import asyncio
import logging
import time
import signal
import sys
from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import TelegramNetworkError, TelegramAPIError, TelegramServerError

# На Windows используем WindowsSelectorEventLoopPolicy, чтобы избежать
# ошибок закрытия цикла при остановке (Ctrl+C)
if sys.platform.startswith("win"):
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except Exception:
        pass
from bot.services.answer_db import init_db, init_progress_table, close_all_connections
init_db()
init_progress_table() 
from bot.handlers.menu import router as menu_router
from bot.handlers.topics import router as topics_router
from bot.handlers.tests import router as tests_router
from bot.handlers import tests_oge
from bot.handlers.tests_teacher import router as tests_teacher_router

from bot.handlers.flashcards import router as flashcards_router
from bot.handlers.billing import router as billing_router
from bot.services.plan import init_billing_tables
from bot.handlers.admin import router as admin_router
# from bot.handlers.giveaway import router as giveaway_router  # Розыгрыш отключен

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
shutdown_requested = False

def signal_handler(signum, frame):
    """Обработчик сигналов для graceful shutdown"""
    print(f"\nПолучен сигнал {signum}. Завершаем работу бота...")
    global shutdown_requested
    shutdown_requested = True
    try:
        loop = asyncio.get_event_loop()
        if bot_instance:
            loop.create_task(shutdown_bot())
    except Exception:
        pass

async def shutdown_bot():
    """Graceful shutdown бота с улучшенным закрытием сессий"""
    global bot_instance, dp_instance, cleanup_task
    try:
        print("🛑 Начинаем остановку бота...")
        
        # Останавливаем cleanup task
        if cleanup_task:
            cleanup_task.cancel()
            try:
                await asyncio.wait_for(cleanup_task, timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
        
        # Останавливаем polling
        if dp_instance:
            try:
                await asyncio.wait_for(dp_instance.stop_polling(), timeout=10.0)
            except (RuntimeError, asyncio.TimeoutError) as e:
                if "Polling is not started" not in str(e):
                    print(f"⚠️ Ошибка при остановке polling: {e}")
        
        # Закрываем сессию бота
        if bot_instance:
            try:
                await asyncio.wait_for(bot_instance.session.close(), timeout=10.0)
            except Exception as e:
                print(f"⚠️ Ошибка при закрытии сессии бота: {e}")
        
        # Закрываем все соединения с базой данных
        close_all_connections()
        
        # Даем время на завершение всех задач
        await asyncio.sleep(0.5)
        
        print("✅ Бот успешно остановлен")
    except Exception as e:
        print(f"❌ Ошибка при остановке бота: {e}")

# Регистрируем обработчики сигналов
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

async def set_bot_commands(bot: Bot):
    """Устанавливает команды бота с улучшенной обработкой ошибок"""
    commands = [
        BotCommand(command="start", description="Начать работу с ботом"),
        BotCommand(command="menu", description="Главное меню"),
        BotCommand(command="help", description="Как работает бот"),
        BotCommand(command="report", description="Получить отчёт"),
        BotCommand(command="resume", description="Продолжить курс"),
        BotCommand(command="tests", description="Пройти тесты"),
        # BotCommand(command="giveaway", description="🎁 Участвовать в розыгрыше"),  # Розыгрыш отключен
        BotCommand(command="stats", description="📊 Статистика бота (админ)"),
        BotCommand(command="stats_clean", description="📊 Статистика без админов (админ)"),
        BotCommand(command="help_admin", description="🛠️ Справка по админским командам"),
        BotCommand(command="retention_week", description="📈 Удержание за неделю (админ)"),
        # BotCommand(command="giveaway_stats", description="🎁 Статистика розыгрыша (админ)"),  # Розыгрыш отключен
        # BotCommand(command="giveaway_draw", description="🎊 Провести розыгрыш (админ)"),      # Розыгрыш отключен
        # BotCommand(command="giveaway_draw_today", description="🎊 Розыгрыш среди сегодняшних (админ)"),  # Розыгрыш отключен
    ]
    
    max_retries = 1  # Только одна попытка для быстрого запуска
    for attempt in range(max_retries):
        try:
            # Быстрый таймаут для быстрого запуска
            await asyncio.wait_for(
                bot.set_my_commands(commands),
                timeout=3.0  # Всего 3 секунды
            )
            print("✅ Команды бота установлены успешно")
            return True
        except (asyncio.TimeoutError, TelegramNetworkError, TelegramServerError, Exception):
            # Любая ошибка - сразу выходим без задержек
            break
    
    print("⚠️ Не удалось установить команды бота, но бот будет работать")
    return False

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
    dp_instance.include_router(tests_teacher_router) # Задания от преподавателя
    dp_instance.include_router(flashcards_router)
    dp_instance.include_router(admin_router)     # Админские команды
    # dp_instance.include_router(giveaway_router)  # Розыгрыш отключен

    # --- Установка команд (не критично, если не получится) ---
    print("🔧 Устанавливаем команды бота...")
    commands_set = await set_bot_commands(bot_instance)
    if not commands_set:
        print("⚠️ Команды бота не установлены, но бот будет работать")

    # --- Запуск rate limiter cleanup ---
    cleanup_task = asyncio.create_task(cleanup_rate_limiters())

    # --- Проверка токена перед запуском ---
    try:
        print("🔍 Проверяем токен бота...")
        bot_info = await bot_instance.get_me()
        print(f"✅ Бот подключен: @{bot_info.username} ({bot_info.first_name})")
    except Exception as e:
        print(f"❌ Ошибка подключения к боту: {e}")
        print("⚠️ Проверьте токен в .env файле")
        return

    # --- Запуск polling с улучшенной обработкой ошибок ---
    print("🚀 Бот запущен! Готов к работе!")
    print("📊 Ожидаемая нагрузка: 150-200 пользователей одновременно")
    print("🛡️ Rate limiting включен для защиты от спама")
    
    retry_delay = 1  # Быстрый перезапуск
    max_retry_delay = 10  # Максимальная задержка
    
    while not shutdown_requested:
        try:
            print("🔄 Запускаем polling...")
            print("⏱️ Таймаут: 10 секунд на подключение...")
            await dp_instance.start_polling(
                bot_instance, 
                polling_timeout=10,  # Еще меньше для быстрого обнаружения проблем
                timeout=8,           # Быстрый timeout
                fast=True            # Быстрый режим polling
            )
        except TelegramNetworkError as e:
            print(f"🌐 Проблема с сетью: {e}")
            print(f"⏳ Ждем {retry_delay} секунд перед повторной попыткой...")
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 1.5, max_retry_delay)  # Более мягкое увеличение задержки
        except (TelegramAPIError, TelegramServerError) as e:
            if "Bad Gateway" in str(e) or "Internal Server Error" in str(e):
                print("⚠️ Проблемы с серверами Telegram, ждем 5 секунд...")
                await asyncio.sleep(5)  # Быстрее при проблемах с сервером
                retry_delay = 1  # Сбрасываем задержку
            else:
                print(f"❌ Ошибка Telegram API: {e}")
                print(f"⏳ Ждем {retry_delay} секунд...")
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 1.5, max_retry_delay)
        except KeyboardInterrupt:
            print("\n🛑 Бот остановлен пользователем")
            break
        except Exception as e:
            print(f"❌ Неожиданная ошибка: {e}")
            print(f"⏳ Ждем {retry_delay} секунд...")
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 1.5, max_retry_delay)

if __name__ == "__main__":
    asyncio.run(main())
