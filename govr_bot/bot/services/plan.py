import sqlite3
from datetime import datetime, date
from typing import Optional, Tuple

from bot.services.answer_db import DB_FILE


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
    with sqlite3.connect(DB_FILE) as conn:
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
    with sqlite3.connect(DB_FILE) as conn:
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
    with sqlite3.connect(DB_FILE) as conn:
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
        }
    if plan == ORGANIC:
        return {
            "theory_voice_per_day": 5,
            "theory_ai_per_day": 20,
            "test_explain_per_day": 100,
            "test_hint_per_day": 100,
            "reports_per_month": 5,
        }
    if plan == ELEMENTS:
        return {
            "theory_voice_per_day": 5,
            "theory_ai_per_day": 20,
            "test_explain_per_day": 100,
            "test_hint_per_day": 100,
            "reports_per_month": 5,
        }
    # FREE
    return {
        "theory_voice_per_day": 1,
        "theory_ai_per_day": 2,
        "test_explain_per_day": 3,
        "test_hint_per_day": 5,
        "reports_per_month": 1,
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
    with sqlite3.connect(DB_FILE) as conn:
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


