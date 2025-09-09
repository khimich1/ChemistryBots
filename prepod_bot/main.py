from aiogram import Bot, Dispatcher
from config import BOT_TOKEN
from handlers import menu, online, report, add_task

print("[LOG] main.py ЗАПУЩЕН")
print(f"[LOG] BOT_TOKEN (начало): {BOT_TOKEN[:10]}...")

bot = Bot(token=BOT_TOKEN)
print("[LOG] Bot object создан")

dp = Dispatcher()
print("[LOG] Dispatcher создан")

# Подключаем все роутеры
dp.include_router(menu.router)
print("[LOG] Router menu registered")
dp.include_router(online.router)
print("[LOG] Router online registered")
dp.include_router(report.router)
print("[LOG] Router report registered")
dp.include_router(add_task.router)
print("[LOG] Router add_task registered")

if __name__ == "__main__":
    import asyncio
    print("[LOG] Перед dp.start_polling(bot)")

    async def _run():
        # Убираем webhook, чтобы не было конфликта с polling
        try:
            info = await bot.get_webhook_info()
            print(f"[LOG] Webhook BEFORE: {getattr(info, 'url', '')!r}")
        except Exception as e:
            print(f"[LOG] get_webhook_info error: {e}")

        try:
            await bot.delete_webhook(drop_pending_updates=True)
            print("[LOG] Webhook deleted (drop_pending_updates=True)")
        except Exception as e:
            print(f"[LOG] delete_webhook error: {e}")

        # Запуск фонового оповещателя онлайн-активности
        try:
            from handlers import online as online_handlers
            asyncio.create_task(online_handlers.start_notifier(bot))
            print("[LOG] Online notifier started")
        except Exception as e:
            print(f"[LOG] start_notifier error: {e}")

        await dp.start_polling(bot)

    try:
        asyncio.run(_run())
    except Exception as e:
        print(f"[LOG] Ошибка при запуске polling: {e}")
