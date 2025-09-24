import os
import sqlite3
from contextlib import contextmanager
from typing import Dict, Optional


class Database:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self._db_path)
        try:
            yield connection
        finally:
            connection.close()

    def ensure_teacher_table(self) -> None:
        with self.connect() as conn:
            conn.execute(
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

    def upsert_teacher(self, teacher: Dict[str, Optional[str]]) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO teacher (tg_id, nickname, name, moniker, discipline, rate)
                VALUES (:tg_id, :nickname, :name, :moniker, :discipline, :rate)
                ON CONFLICT(tg_id) DO UPDATE SET
                    nickname=excluded.nickname,
                    name=excluded.name,
                    moniker=excluded.moniker,
                    discipline=excluded.discipline,
                    rate=excluded.rate
                """,
                teacher,
            )
            conn.commit()

    def get_teacher_by_tg_id(self, tg_id: int) -> Optional[Dict[str, Optional[str]]]:
        with self.connect() as conn:
            cur = conn.execute(
                "SELECT tg_id, nickname, name, moniker, discipline, rate FROM teacher WHERE tg_id = ?",
                (tg_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return {
                "tg_id": row[0],
                "nickname": row[1],
                "name": row[2],
                "moniker": row[3],
                "discipline": row[4],
                "rate": row[5],
            }


_DB: Optional[Database] = None


def set_default_db(db: Database) -> None:
    global _DB
    _DB = db


def get_db() -> Database:
    assert _DB is not None, "Database is not initialized. Call set_default_db() first."
    return _DB
