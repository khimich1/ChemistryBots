import sqlite3
from typing import Optional

from config import USERS_DB


def get_teacher_moniker(tg_id: int) -> Optional[str]:
    """
    Возвращает moniker преподавателя из таблицы teacher или None, если не найден/пусто.
    """
    try:
        with sqlite3.connect(USERS_DB) as conn:
            cur = conn.cursor()
            cur.execute("SELECT moniker FROM teacher WHERE tg_id=?", (tg_id,))
            row = cur.fetchone()
            if not row:
                return None
            moniker = (row[0] or "").strip()
            return moniker or None
    except Exception:
        return None


def _current_teacher_columns(cur: sqlite3.Cursor) -> set[str]:
    cur.execute("PRAGMA table_info(teacher)")
    return {row[1] for row in cur.fetchall()}


def ensure_teacher_schema() -> None:
    """
    Приводит таблицу teacher к единой схеме:
      tg_id INTEGER PRIMARY KEY,
      nickname TEXT,
      name TEXT,
      moniker TEXT,
      discipline TEXT,
      rate TEXT,
      ical_url TEXT

    Старые колонки (google_id, yandex_url, yandex_ics) будут отброшены/скопированы в ical_url при миграции.
    """
    try:
        with sqlite3.connect(USERS_DB) as conn:
            cur = conn.cursor()
            try:
                cols = _current_teacher_columns(cur)
            except Exception:
                cols = set()
            desired = {"tg_id", "nickname", "name", "moniker", "discipline", "rate", "ical_url"}
            if not cols:
                # Если таблицы ещё нет — создадим нужную
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS teacher (
                        tg_id INTEGER PRIMARY KEY,
                        nickname TEXT,
                        name TEXT,
                        moniker TEXT,
                        discipline TEXT,
                        rate TEXT,
                        ical_url TEXT
                    )
                    """
                )
                conn.commit()
                return

            # Если уже совместимо — ничего не делаем
            if desired.issubset(cols) and cols.issubset(desired):
                return

            # Миграция через новую таблицу
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS teacher_new (
                    tg_id INTEGER PRIMARY KEY,
                    nickname TEXT,
                    name TEXT,
                    moniker TEXT,
                    discipline TEXT,
                    rate TEXT,
                    ical_url TEXT
                )
                """
            )

            parts = [
                "tg_id",
                "NULL AS nickname",
                "NULL AS name",
                ("moniker" if "moniker" in cols else "NULL AS moniker"),
                "NULL AS discipline",
                "NULL AS rate",
            ]
            if "ical_url" in cols:
                parts.append("ical_url AS ical_url")
            elif "yandex_ics" in cols:
                parts.append("yandex_ics AS ical_url")
            else:
                parts.append("NULL AS ical_url")

            select_sql = "SELECT " + ", ".join(parts) + " FROM teacher"
            cur.execute(
                f"INSERT INTO teacher_new (tg_id, nickname, name, moniker, discipline, rate, ical_url) {select_sql}"
            )

            cur.execute("DROP TABLE teacher")
            cur.execute("ALTER TABLE teacher_new RENAME TO teacher")
            conn.commit()
    except Exception:
        # не падаем в рантайме
        pass


def _ensure_teacher_ical_column() -> None:
    """
    Гарантирует наличие колонки ical_url в таблице teacher.
    Безопасная миграция: если колонки нет — добавляем.
    """
    try:
        with sqlite3.connect(USERS_DB) as conn:
            cur = conn.cursor()
            # Приводим схему перед проверкой
            ensure_teacher_schema()
            cur.execute("PRAGMA table_info(teacher)")
            cols = {row[1] for row in cur.fetchall()}
            if "ical_url" not in cols:
                cur.execute("ALTER TABLE teacher ADD COLUMN ical_url TEXT")
                conn.commit()
    except Exception:
        # Тихо игнорируем: если нет таблицы или нет прав — просто не используем iCal
        pass


def get_teacher_ical_url(tg_id: int) -> Optional[str]:
    """
    Возвращает iCal URL преподавателя или None, если не задан.
    """
    _ensure_teacher_ical_column()
    try:
        with sqlite3.connect(USERS_DB) as conn:
            cur = conn.cursor()
            # Попробуем сначала ical_url, затем yandex_ics (совместимость со старой схемой)
            cur.execute("PRAGMA table_info(teacher)")
            cols = {row[1] for row in cur.fetchall()}

            if "ical_url" in cols:
                cur.execute("SELECT ical_url FROM teacher WHERE tg_id=?", (tg_id,))
                row = cur.fetchone()
                if row:
                    value = (row[0] or "").strip()
                    if value:
                        return value

            if "yandex_ics" in cols:
                cur.execute("SELECT yandex_ics FROM teacher WHERE tg_id=?", (tg_id,))
                row = cur.fetchone()
                if row:
                    value = (row[0] or "").strip()
                    if value:
                        return value
            return None
    except Exception:
        return None


def set_teacher_ical_url(tg_id: int, url: str) -> bool:
    """
    Сохраняет iCal URL для преподавателя. Возвращает True при успехе.
    Предполагаем, что запись teacher уже существует (создаётся через admin_bot).
    """
    _ensure_teacher_ical_column()
    url = (url or "").strip()
    try:
        with sqlite3.connect(USERS_DB) as conn:
            cur = conn.cursor()
            # Обновим обе колонки, если они есть
            cur.execute("PRAGMA table_info(teacher)")
            cols = {row[1] for row in cur.fetchall()}

            updated = 0
            if "ical_url" in cols:
                cur.execute("UPDATE teacher SET ical_url=? WHERE tg_id=?", (url, tg_id))
                updated += cur.rowcount or 0
            if "yandex_ics" in cols:
                cur.execute("UPDATE teacher SET yandex_ics=? WHERE tg_id=?", (url, tg_id))
                updated += cur.rowcount or 0
            conn.commit()
            return updated > 0
    except Exception:
        return False

