import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "").split(","))) if os.getenv("ADMIN_IDS") else []
DB_PATH = os.getenv("DB_PATH")  # путь к базе активности (test_answers.db)
TESTS_DB_PATH = os.getenv("TESTS_DB_PATH")  # путь к базе с тестами (tests1.db)
ONLINE_WINDOW_MINUTES = int(os.getenv("ONLINE_WINDOW_MINUTES", 10))
