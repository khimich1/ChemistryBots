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
    try:
        asyncio.run(dp.start_polling(bot))
    except Exception as e:
        print(f"[LOG] Ошибка при запуске polling: {e}")
