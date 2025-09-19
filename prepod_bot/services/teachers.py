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


