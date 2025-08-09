import os
from dotenv import load_dotenv

# Загружаем переменные из файла .env (должен лежать рядом с config.py или main.py)
load_dotenv()

# === Токен Telegram-бота для преподавателя ===
BOT_TOKEN = os.getenv("BOT_TOKEN")

# === Список ID преподавателей (можно несколько через запятую) ===
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x]

# === Путь к общей базе данных ===
DB_PATH = os.getenv("DB_PATH")

# === Другие параметры (можно добавлять по ходу дела) ===
ONLINE_WINDOW_MINUTES = 10  # За сколько минут считать ученика "онлайн"
HISTORY_LIMIT = 20          # Сколько последних ответов показывать по истории
