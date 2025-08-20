import os
import sqlite3
from datetime import datetime

from config import DB_PATH, TESTS_DB_PATH


def _ensure_debug_table(conn: sqlite3.Connection) -> None:
    c = conn.cursor()
    c.execute(
        '''CREATE TABLE IF NOT EXISTS test_debug (
               question_id INTEGER PRIMARY KEY,
               reason TEXT,
               status TEXT DEFAULT 'не решено'
           )'''
    )
    conn.commit()


def list_problem_tasks() -> list[dict]:
    """Возвращает список скрытых (проблемных) заданий из tests1.db,
    опираясь на столбец has_issue=1.
    """
    tasks: list[dict] = []
    with sqlite3.connect(TESTS_DB_PATH) as conn:
        c = conn.cursor()
        # Гарантируем наличие колонок (если модуль govr_bot их ещё не добавил)
        cols = {row[1] for row in c.execute("PRAGMA table_info(tests)")}
        if "has_issue" not in cols:
            try:
                c.execute("ALTER TABLE tests ADD COLUMN has_issue INTEGER DEFAULT 0")
                c.execute("ALTER TABLE tests ADD COLUMN issue_reason TEXT DEFAULT ''")
                c.execute("ALTER TABLE tests ADD COLUMN issue_reported_at TEXT DEFAULT ''")
                conn.commit()
            except Exception:
                pass
        for row in c.execute(
            "SELECT id, question, options, COALESCE(correct_answer, ''), COALESCE(hint, '') FROM tests WHERE COALESCE(has_issue,0)=1 ORDER BY id"
        ):
            tasks.append({
                "id": row[0],
                "question": row[1] or "",
                "options": row[2] or "",
                "correct_answer": row[3] or "",
                "hint": row[4] or "",
            })
    return tasks


def get_task_by_id(task_id: int) -> dict | None:
    with sqlite3.connect(TESTS_DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            "SELECT id, question, options, COALESCE(correct_answer,''), COALESCE(hint,'') FROM tests WHERE id=?",
            (int(task_id),)
        )
        row = c.fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "question": row[1] or "",
            "options": row[2] or "",
            "correct_answer": row[3] or "",
            "hint": row[4] or "",
        }


def update_task_field(task_id: int, field: str, new_text: str) -> None:
    if field not in {"question", "options", "correct_answer", "hint"}:
        return
    with sqlite3.connect(TESTS_DB_PATH) as conn:
        c = conn.cursor()
        c.execute(f"UPDATE tests SET {field}=? WHERE id=?", (new_text, int(task_id)))
        conn.commit()


def unhide_task(task_id: int) -> None:
    # 1) tests1.db: снимаем флаг has_issue
    with sqlite3.connect(TESTS_DB_PATH) as conn:
        c = conn.cursor()
        c.execute("UPDATE tests SET has_issue=0 WHERE id=?", (int(task_id),))
        conn.commit()
    # 2) test_answers.db: помечаем complaint как 'решено'
    with sqlite3.connect(DB_PATH) as conn:
        _ensure_debug_table(conn)
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO test_debug (question_id, reason, status)
            VALUES (?, COALESCE((SELECT reason FROM test_debug WHERE question_id=?), ''), 'решено')
            ON CONFLICT(question_id) DO UPDATE SET status='решено'
            """,
            (int(task_id), int(task_id))
        )
        conn.commit()

