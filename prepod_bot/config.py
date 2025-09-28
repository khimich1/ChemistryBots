import os
from dotenv import load_dotenv

load_dotenv()
_LOCAL_ENV = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(_LOCAL_ENV):
    load_dotenv(_LOCAL_ENV, override=True)

# Абсолютные пути к корню репозитория и каталогу shared
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.normpath(os.path.join(_THIS_DIR, ".."))
_SHARED_DIR = os.path.join(_REPO_ROOT, "shared")
_FONTS_DIR_DEFAULT = os.path.join(_SHARED_DIR, "Fonts")

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "").split(","))) if os.getenv("ADMIN_IDS") else []

# Настройки ссылок (deep-link и подсказки)
# Пример: https://t.me/ИмяБота?start=ads1
DEEPLINK_HINT = os.getenv("DEEPLINK_HINT", "https://t.me/ИмяБота?start=ads1")

# Если переменные окружения не заданы, используем дефолтные базы из shared/
DB_PATH = os.getenv("DB_PATH") or os.path.join(_SHARED_DIR, "test_answers.db")
# База с заданиями ЕГЭ/ОГЭ. Старое TESTS_DB_PATH (tests1.db) больше не используется
# Для ЕГЭ используем TESTS_DB_EGE (дефолт: shared/test_ege.db)
TESTS_DB_EGE = os.getenv("TESTS_DB_EGE") or os.path.join(_SHARED_DIR, "test_ege.db")
# Для ОГЭ используем TESTS_DB_OGE (дефолт: shared/test_oge.db)
TESTS_DB_OGE = os.getenv("TESTS_DB_OGE") or os.path.join(_SHARED_DIR, "test_oge.db")

# Путь к базе пользователей (регистрируется через admin_bot, таблица teacher)
# По умолчанию shared/users.db рядом с репозиторием
def _clean_path(value: str | None) -> str | None:
    if not value:
        return value
    v = value.strip().strip('"').strip("'")
    return v

USERS_DB = _clean_path(os.getenv("USERS_DB")) or os.path.join(_SHARED_DIR, "users.db")

# Локальный календарь (по просьбе сделать полностью локальным)
CALENDAR_DB = _clean_path(os.getenv("CALENDAR_DB")) or os.path.join(_SHARED_DIR, "calendar.db")

ONLINE_WINDOW_MINUTES = int(os.getenv("ONLINE_WINDOW_MINUTES", 10))

# Ресурсы PDF/шрифтов
FONTS_DIR = os.getenv("FONTS_DIR") or _FONTS_DIR_DEFAULT
FONT_REGULAR = os.getenv("FONT_REGULAR") or os.path.join(FONTS_DIR, "LiberationSerif-Regular.ttf")
FONT_BOLD = os.getenv("FONT_BOLD") or os.path.join(FONTS_DIR, "LiberationSerif-Bold.ttf")
PDF_BASE_IMAGE = os.getenv("PDF_BASE_IMAGE") or os.path.join(FONTS_DIR, "PDF_base.png")
