import os
import sqlite3
from typing import List, Tuple
from config import DB_PATH


def get_ad_stats() -> List[Tuple[str, int, int]]:
    """
    Возвращает список (tag, started, subscribed) из таблицы acquisition в DB_PATH.
    Если таблицы нет — пустой список.
    """
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                SELECT COALESCE(NULLIF(start_param, ''), '(empty)') AS tag,
                       COUNT(*) AS started,
                       SUM(CASE WHEN TRIM(COALESCE(subscribed_at, '')) <> '' THEN 1 ELSE 0 END) AS subscribed
                FROM acquisition
                GROUP BY tag
                ORDER BY started DESC
                """
            )
            rows = cur.fetchall() or []
        except sqlite3.OperationalError:
            # Таблицы нет — вернём пусто
            rows = []
    # Приводим типы
    out: List[Tuple[str, int, int]] = []
    for tag, started, subscribed in rows:
        out.append((str(tag), int(started or 0), int(subscribed or 0)))
    return out


