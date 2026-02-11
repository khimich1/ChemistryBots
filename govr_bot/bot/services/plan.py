import sqlite3
from datetime import datetime, date
from typing import Optional, Tuple

from bot.services.answer_db import DB_FILE, get_conn


# Коды тарифов (простые строковые константы)
FREE = "free"
GROUP = "group"
SELF = "self"
ORGANIC = "organic"
ELEMENTS = "elements"
FULL = "full"


def _today_str() -> str:
    return date.today().strftime("%Y-%m-%d")


def _year_month() -> str:
    d = date.today()
    return f"{d.year:04d}-{d.month:02d}"


def init_billing_tables() -> None:
    """Создаёт необходимые таблицы в общей БД DB_FILE (если их ещё нет)."""
    with get_conn() as conn:
        c = conn.cursor()
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS user_plans(
                user_id INTEGER PRIMARY KEY,
                plan_code TEXT,
                started_at TEXT
            )
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_counters(
                user_id INTEGER,
                counter_key TEXT,
                day TEXT,
                used INTEGER,
                PRIMARY KEY (user_id, counter_key, day)
            )
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS monthly_counters(
                user_id INTEGER,
                counter_key TEXT,
                ym TEXT,
                used INTEGER,
                PRIMARY KEY (user_id, counter_key, ym)
            )
            """
        )
        conn.commit()


def set_user_plan(user_id: int, plan_code: str) -> None:
    """Сохраняет тариф для пользователя."""
    init_billing_tables()
    with get_conn() as conn:
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO user_plans(user_id, plan_code, started_at)
            VALUES(?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET plan_code=excluded.plan_code
            """,
            (int(user_id), plan_code or FREE, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )
        conn.commit()


def get_user_plan_code(user_id: int) -> str:
    """Возвращает код тарифа. По умолчанию — FREE."""
    init_billing_tables()
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT plan_code FROM user_plans WHERE user_id=?", (int(user_id),))
        row = c.fetchone()
        return str(row[0]) if row and row[0] else FREE


def limits_for(plan_code: str) -> dict:
    """Возвращает словарь лимитов для тарифа.

    Ключи, которые используются в проекте:
      - theory_voice_per_day
      - theory_ai_per_day
      - test_explain_per_day
      - test_hint_per_day
      - reports_per_month
      - task_solver_per_month
    """
    plan = (plan_code or FREE).lower()
    if plan in {FULL, GROUP, SELF}:
        # По сути — безлимитно в рамках разумного
        return {
            "theory_voice_per_day": 10,
            "theory_ai_per_day": 50,
            "test_explain_per_day": 200,
            "test_hint_per_day": 200,
            "reports_per_month": 20,
            "task_solver_per_month": 100,
        }
    if plan == ORGANIC:
        return {
            "theory_voice_per_day": 5,
            "theory_ai_per_day": 20,
            "test_explain_per_day": 100,
            "test_hint_per_day": 100,
            "reports_per_month": 5,
            "task_solver_per_month": 100,
        }
    if plan == ELEMENTS:
        return {
            "theory_voice_per_day": 5,
            "theory_ai_per_day": 20,
            "test_explain_per_day": 100,
            "test_hint_per_day": 100,
            "reports_per_month": 5,
            "task_solver_per_month": 100,
        }
    # FREE
    return {
        "theory_voice_per_day": 1,
        "theory_ai_per_day": 2,
        "test_explain_per_day": 3,
        "test_hint_per_day": 5,
        "reports_per_month": 1,
        "task_solver_per_month": 20,
    }


def _consume_generic(
    user_id: int,
    key: str,
    limit: Optional[int],
    *,
    scope: str,
) -> Tuple[bool, int]:
    """Вспомогательная функция учёта.

    scope: "daily" | "monthly"
    Возвращает (ok, left).
    """
    if limit is None:
        return True, 999_999

    init_billing_tables()
    with get_conn() as conn:
        c = conn.cursor()
        if scope == "daily":
            day = _today_str()
            c.execute(
                "SELECT used FROM daily_counters WHERE user_id=? AND counter_key=? AND day=?",
                (int(user_id), key, day),
            )
            row = c.fetchone()
            used = int(row[0]) if row and row[0] is not None else 0
            if used >= int(limit):
                return False, 0
            used += 1
            c.execute(
                """
                INSERT INTO daily_counters(user_id, counter_key, day, used)
                VALUES(?, ?, ?, ?)
                ON CONFLICT(user_id, counter_key, day) DO UPDATE SET used=excluded.used
                """,
                (int(user_id), key, day, used),
            )
            conn.commit()
            return True, max(0, int(limit) - used)
        else:
            ym = _year_month()
            c.execute(
                "SELECT used FROM monthly_counters WHERE user_id=? AND counter_key=? AND ym=?",
                (int(user_id), key, ym),
            )
            row = c.fetchone()
            used = int(row[0]) if row and row[0] is not None else 0
            if used >= int(limit):
                return False, 0
            used += 1
            c.execute(
                """
                INSERT INTO monthly_counters(user_id, counter_key, ym, used)
                VALUES(?, ?, ?, ?)
                ON CONFLICT(user_id, counter_key, ym) DO UPDATE SET used=excluded.used
                """,
                (int(user_id), key, ym, used),
            )
            conn.commit()
            return True, max(0, int(limit) - used)


def consume_daily(user_id: int, key: str, limit: int) -> Tuple[bool, int]:
    """Учесть разовое действие в дневном лимите."""
    return _consume_generic(user_id, key, limit, scope="daily")


def consume_monthly(user_id: int, key: str, limit: int) -> Tuple[bool, int]:
    """Учесть разовое действие в месячном лимите."""
    return _consume_generic(user_id, key, limit, scope="monthly")


def theory_allowed(user_id: int, section: str) -> bool:
    """Проверка доступа к разделам теории по тарифу.

    section: "begin" | "elements" | "organic"
    """
    p = get_user_plan_code(user_id)
    if section == "begin":
        return True
    if section == "elements":
        return p in {ELEMENTS, SELF, GROUP, FULL}
    if section == "organic":
        return p in {ORGANIC, SELF, GROUP, FULL}
    return False


def flashcards_mode_allowed(user_id: int, mode: str, category: str) -> bool:
    """Проверка доступа к режимам карточек по тарифу.
    
    mode: "practice" | "errors"
    category: "inorg" | "org"
    """
    p = get_user_plan_code(user_id)
    
    # Заучивание доступно всем
    if mode == "learn":
        return True
    
    # Практика и работа над ошибками доступны только на платных тарифах
    if mode in {"practice", "errors"}:
        return p in {ORGANIC, ELEMENTS, SELF, GROUP, FULL}
    
    return False


def get_task_solver_remaining(user_id: int) -> Tuple[int, int]:
    """
    Возвращает количество оставшихся запросов к решатору задач.
    
    Returns:
        Tuple[int, int]: (осталось_запросов, всего_запросов)
    """
    plan = get_user_plan_code(user_id)
    limits = limits_for(plan)
    total = limits["task_solver_per_month"]
    
    # Получаем количество использованных запросов
    init_billing_tables()
    with get_conn() as conn:
        c = conn.cursor()
        ym = _year_month()
        c.execute(
            "SELECT used FROM monthly_counters WHERE user_id=? AND counter_key=? AND ym=?",
            (int(user_id), "task_solver", ym),
        )
        row = c.fetchone()
        used = int(row[0]) if row and row[0] is not None else 0
    
    remaining = max(0, total - used)
    return remaining, total


def get_plan_name(plan_code: str) -> str:
    """
    Возвращает человекочитаемое название тарифа.
    """
    plan = (plan_code or FREE).lower()
    names = {
        FREE: "Бесплатный",
        GROUP: "Групповой",
        SELF: "Самоподготовка",
        ORGANIC: "Органическая химия",
        ELEMENTS: "Химия элементов",
        FULL: "Полный доступ",
    }
    return names.get(plan, "Неизвестный")


