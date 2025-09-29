import os
import sqlite3
from datetime import datetime
from typing import Optional

from config import TESTS_DB_TEACHER


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """Создаёт недостающие таблицы по образцу баз ЕГЭ/ОГЭ.

    Таблица tests — совместимая по именам колонок:
      id, type, question, options, correct_ans|correct_answer, explanation, hint, detailed_explanation
    Мы используем колонку correct_ans (как просили), но также создаём alias correct_answer
    для совместимости с клиентским кодом (если колонка отсутствует — добавляем).

    Таблица images — хранит бинарные данные изображений.
    """
    c = conn.cursor()
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS tests (
            id INTEGER PRIMARY KEY,
            filename TEXT,
            type INTEGER,
            question TEXT,
            options TEXT,
            correct_ans TEXT,
            explanation TEXT,
            hint TEXT,
            detailed_explanation TEXT
        )
        """
    )

    # Если нет колонки correct_answer — создадим для совместимости
    c.execute("PRAGMA table_info(tests)")
    cols = {row[1] for row in c.fetchall()}
    if "correct_answer" not in cols:
        try:
            c.execute("ALTER TABLE tests ADD COLUMN correct_answer TEXT")
        except Exception:
            pass

    # Таблица изображений
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT,
            mime_type TEXT,
            size_bytes INTEGER,
            data BLOB,
            created_at TEXT
        )
        """
    )
    conn.commit()


def _connect() -> sqlite3.Connection:
    path = TESTS_DB_TEACHER
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    _ensure_schema(conn)
    return conn


def save_image(filename: str, mime_type: str, data: bytes) -> int:
    """Сохраняет изображение в images и возвращает id."""
    with _connect() as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO images (filename, mime_type, size_bytes, data, created_at) VALUES (?, ?, ?, ?, ?)",
            (filename, mime_type, len(data or b""), data, datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")),
        )
        conn.commit()
        return int(c.lastrowid)


def add_teacher_task(*, teacher_tg_id: int, question_text: str, image_id: Optional[int], correct_answer: str) -> int:
    """Добавляет задание в tests. Поля:
    - filename: Telegram ID преподавателя (как строка)
    - question: текст задания
    - options: ID изображения (или список ID через запятую), если есть; иначе пусто
    - correct_ans: верный ответ (строкой)
    Возвращает id созданной записи.
    """
    options_value = str(image_id) if image_id is not None else ""
    with _connect() as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO tests (filename, type, question, options, correct_ans, correct_answer) VALUES (?, NULL, ?, ?, ?, ?)",
            (str(teacher_tg_id), question_text, options_value, str(correct_answer), str(correct_answer)),
        )
        conn.commit()
        return int(c.lastrowid)


