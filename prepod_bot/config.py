import os
from dotenv import load_dotenv

load_dotenv()

# Абсолютные пути к корню репозитория и каталогу shared
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.normpath(os.path.join(_THIS_DIR, ".."))
_SHARED_DIR = os.path.join(_REPO_ROOT, "shared")

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "").split(","))) if os.getenv("ADMIN_IDS") else []

# Если переменные окружения не заданы, используем дефолтные базы из shared/
DB_PATH = os.getenv("DB_PATH") or os.path.join(_SHARED_DIR, "test_answers.db")
TESTS_DB_PATH = os.getenv("TESTS_DB_PATH") or os.path.join(_SHARED_DIR, "tests1.db")

ONLINE_WINDOW_MINUTES = int(os.getenv("ONLINE_WINDOW_MINUTES", 10))
