from aiogram import Bot, Dispatcher
from config import BOT_TOKEN
from handlers import menu, online, report, add_task
from middlewares.admin_check import AdminCheckMiddleware
import logging
from logging.handlers import RotatingFileHandler

# Логирование в файл с ротацией
logger = logging.getLogger("prepod_bot")
logger.setLevel(logging.INFO)
_handler = RotatingFileHandler("prepod_bot.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
_handler.setFormatter(_fmt)
logger.addHandler(_handler)

logger.info("main.py ЗАПУЩЕН")
logger.info("BOT_TOKEN загружен" if BOT_TOKEN else "BOT_TOKEN НЕ НАЙДЕН!")

bot = Bot(token=BOT_TOKEN)
logger.info("Bot object создан")

dp = Dispatcher()
logger.info("Dispatcher создан")

# Подключаем middleware для проверки прав доступа
dp.message.middleware(AdminCheckMiddleware())
dp.callback_query.middleware(AdminCheckMiddleware())
logger.info("AdminCheckMiddleware подключен")

# Подключаем все роутеры
dp.include_router(menu.router)
logger.info("Router menu registered")
dp.include_router(online.router)
logger.info("Router online registered")
dp.include_router(report.router)
logger.info("Router report registered")
dp.include_router(add_task.router)
logger.info("Router add_task registered")

if __name__ == "__main__":
    import asyncio
    logger.info("Перед dp.start_polling(bot)")

    async def _run():
        # Убираем webhook, чтобы не было конфликта с polling
        try:
            info = await bot.get_webhook_info()
            logger.info(f"Webhook BEFORE: {getattr(info, 'url', '')!r}")
        except Exception as e:
            logger.exception(f"get_webhook_info error: {e}")

        try:
            await bot.delete_webhook(drop_pending_updates=True)
            logger.info("Webhook deleted (drop_pending_updates=True)")
        except Exception as e:
            logger.exception(f"delete_webhook error: {e}")

        # Запуск фонового оповещателя онлайн-активности
        try:
            from handlers import online as online_handlers
            asyncio.create_task(online_handlers.start_notifier(bot))
            logger.info("Online notifier started")
        except Exception as e:
            logger.exception(f"start_notifier error: {e}")

        await dp.start_polling(bot)

    try:
        asyncio.run(_run())
    except Exception as e:
        logger.exception(f"Ошибка при запуске polling: {e}")
