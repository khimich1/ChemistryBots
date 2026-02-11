import sqlite3
from typing import Optional, Dict

from config import USERS_DB


def _ensure_teacher_table(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS teacher (
            tg_id INTEGER PRIMARY KEY,
            nickname TEXT,
            name TEXT NOT NULL,
            moniker TEXT,
            discipline TEXT,
            rate TEXT
        )
        """
    )
    conn.commit()


def get_teacher_moniker(tg_id: int) -> Optional[str]:
    """
    Возвращает moniker преподавателя из таблицы teacher или None, если не найден/пусто.
    """
    try:
        with sqlite3.connect(USERS_DB) as conn:
            _ensure_teacher_table(conn)
            cur = conn.cursor()
            cur.execute("SELECT moniker FROM teacher WHERE tg_id=?", (tg_id,))
            row = cur.fetchone()
            if not row:
                return None
            moniker = (row[0] or "").strip()
            return moniker or None
    except Exception:
        return None


def upsert_teacher_minimal(*, tg_id: int, name: str, nickname: Optional[str] = None, moniker: Optional[str] = None) -> None:
    """Создаёт или обновляет запись преподавателя с обязательным полем name.
    Остальные поля оставляем пустыми, если не переданы.
    """
    try:
        with sqlite3.connect(USERS_DB) as conn:
            _ensure_teacher_table(conn)
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO teacher (tg_id, nickname, name, moniker, discipline, rate)
                VALUES (?, ?, ?, ?, NULL, NULL)
                ON CONFLICT(tg_id) DO UPDATE SET
                    nickname=excluded.nickname,
                    name=excluded.name,
                    moniker=excluded.moniker
                """,
                (int(tg_id), (nickname or None), name.strip(), (moniker or None)),
            )
            conn.commit()
    except Exception:
        # Тихо игнорируем — бот продолжит работу, а повторная попытка будет при следующем старте
        pass


def get_teacher_record(tg_id: int) -> Optional[Dict[str, Optional[str]]]:
    try:
        with sqlite3.connect(USERS_DB) as conn:
            _ensure_teacher_table(conn)
            cur = conn.cursor()
            cur.execute(
                "SELECT tg_id, nickname, name, moniker, discipline, rate FROM teacher WHERE tg_id=?",
                (int(tg_id),),
            )
            row = cur.fetchone()
            if not row:
                return None
            return {
                "tg_id": int(row[0]),
                "nickname": row[1],
                "name": row[2],
                "moniker": row[3],
                "discipline": row[4],
                "rate": row[5],
            }
    except Exception:
        return None


