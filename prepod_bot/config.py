import os
from dotenv import load_dotenv

load_dotenv()

# Абсолютные пути к корню репозитория и каталогу shared
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.normpath(os.path.join(_THIS_DIR, ".."))
_SHARED_DIR = os.path.join(_REPO_ROOT, "shared")
_FONTS_DIR_DEFAULT = os.path.join(_SHARED_DIR, "Fonts")

# Утилиты для безопасной обработки путей из .env (без изменения .env)
def _expand_path(value: str | None) -> str | None:
    """Разворачивает $VARS и ~, убирает кавычки. Возвращает абсолютный путь,
    если был относительный — относительно корня репозитория.
    Ничего в окружении не меняет.
    """
    if not value:
        return value
    v = value.strip().strip('"').strip("'")
    v = os.path.expandvars(os.path.expanduser(v))
    if not os.path.isabs(v):
        v = os.path.normpath(os.path.join(_REPO_ROOT, v))
    return v

def _sub_vars(value: str | None, mapping: dict[str, str]) -> str | None:
    if not value:
        return value
    out = value
    for key, val in mapping.items():
        out = out.replace(f"${key}", val).replace(f"${{{key}}}", val)
    return out

def _first_existing_file(paths: list[str | None]) -> str | None:
    """Возвращает первый реально существующий файл из списка путей.
    Игнорирует None и пустые строки.
    """
    for p in paths:
        if not p:
            continue
        try:
            if os.path.isfile(p):
                return p
        except Exception:
            # На всякий случай не валимся на ошибках доступа
            continue
    return None

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "").split(","))) if os.getenv("ADMIN_IDS") else []

# Настройки ссылок (deep-link и подсказки)
# Пример: https://t.me/ИмяБота?start=ads1
DEEPLINK_HINT = os.getenv("DEEPLINK_HINT", "https://t.me/ИмяБота?start=ads1")

# Если в .env указан путь, но файл отсутствует/недоступен, тихо переключаемся
# на ближайший рабочий вариант, не меняя .env
_DB_ENV = _expand_path(os.getenv("DB_PATH"))
DB_PATH = _first_existing_file([
    _DB_ENV,
    os.path.join(_SHARED_DIR, "test_answers.db"),
    os.path.join(_THIS_DIR, "test_answers.db"),
]) or (os.path.join(_SHARED_DIR, "test_answers.db"))
# База с заданиями ЕГЭ/ОГЭ. Старое TESTS_DB_PATH (tests1.db) больше не используется
# Для ЕГЭ используем TESTS_DB_EGE (дефолт: shared/test_ege.db)
TESTS_DB_EGE = _expand_path(os.getenv("TESTS_DB_EGE")) or os.path.join(_SHARED_DIR, "test_ege.db")
# Для ОГЭ используем TESTS_DB_OGE (дефолт: shared/test_oge.db)
TESTS_DB_OGE = _expand_path(os.getenv("TESTS_DB_OGE")) or os.path.join(_SHARED_DIR, "test_oge.db")

<<<<<<< Updated upstream
# Путь к базе пользователей (регистрируется через admin_bot, таблица teacher)
# По умолчанию shared/users.db рядом с репозиторием
USERS_DB = os.getenv("USERS_DB") or os.path.join(_SHARED_DIR, "users.db")
=======
# База для заданий, добавляемых преподавателями (teacher)
# В .env предусмотрена переменная TESTS_DB_TEACHER с абсолютным путём
TESTS_DB_TEACHER = _expand_path(os.getenv("TESTS_DB_TEACHER")) or os.path.join(_SHARED_DIR, "test_teacher.db")

# Путь к базе пользователей (регистрируется через admin_bot, таблица teacher)
# По умолчанию shared/users.db рядом с репозиторием
def _clean_path(value: str | None) -> str | None:
    if not value:
        return value
    v = value.strip().strip('"').strip("'")
    return v

USERS_DB = _expand_path(_clean_path(os.getenv("USERS_DB"))) or os.path.join(_SHARED_DIR, "users.db")

# Локальный календарь (по просьбе сделать полностью локальным)
CALENDAR_DB = _expand_path(_clean_path(os.getenv("CALENDAR_DB"))) or os.path.join(_SHARED_DIR, "calendar.db")
>>>>>>> Stashed changes

ONLINE_WINDOW_MINUTES = int(os.getenv("ONLINE_WINDOW_MINUTES", 10))

# Ресурсы PDF/шрифтов (с разворачиванием путей и безопасными фолбэками)
FONTS_DIR = _expand_path(os.getenv("FONTS_DIR")) or _FONTS_DIR_DEFAULT
if not os.path.isdir(FONTS_DIR):
    FONTS_DIR = _FONTS_DIR_DEFAULT

_FONT_REG_ENV = _expand_path(_sub_vars(os.getenv("FONT_REGULAR"), {"FONTS_DIR": FONTS_DIR}))
_FONT_BOLD_ENV = _expand_path(_sub_vars(os.getenv("FONT_BOLD"), {"FONTS_DIR": FONTS_DIR}))
_PDF_BASE_ENV = _expand_path(_sub_vars(os.getenv("PDF_BASE_IMAGE"), {"FONTS_DIR": FONTS_DIR}))

FONT_REGULAR = _FONT_REG_ENV or os.path.join(FONTS_DIR, "LiberationSerif-Regular.ttf")
FONT_BOLD = _FONT_BOLD_ENV or os.path.join(FONTS_DIR, "LiberationSerif-Bold.ttf")
PDF_BASE_IMAGE = _PDF_BASE_ENV or os.path.join(FONTS_DIR, "PDF_base.png")
