import os
import sqlite3
from datetime import datetime

from config import DB_PATH, TESTS_DB_EGE


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


def _detect_answer_column(conn: sqlite3.Connection, table: str = "tests") -> str:
    c = conn.cursor()
    c.execute(f"PRAGMA table_info({table})")
    cols = {row[1] for row in c.fetchall()}
    if "correct_answer" in cols:
        return "correct_answer"
    if "correct_ans" in cols:
        return "correct_ans"
    # если ни одной знакомой колонки нет — пусть будет correct_answer, чтобы не падать
    return "correct_answer"


def _ensure_tests_bug(conn: sqlite3.Connection) -> None:
    c = conn.cursor()
    # если нет исходной `tests`, выходим — ничего не сделаем
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tests'")
    if not c.fetchone():
        return
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tests_bug'")
    if not c.fetchone():
        c.execute("CREATE TABLE tests_bug AS SELECT * FROM tests WHERE 0")
        conn.commit()


def list_problem_tasks() -> list[dict]:
    """Возвращает список заданий из таблицы tests_bug (задания в работе/на исправлении)."""
    tasks: list[dict] = []
    with sqlite3.connect(TESTS_DB_EGE) as conn:
        c = conn.cursor()
        _ensure_tests_bug(conn)
        ans_col = _detect_answer_column(conn, "tests_bug")
        sql = (
            f"SELECT id, question, options, COALESCE({ans_col}, ''), COALESCE(hint, '') "
            f"FROM tests_bug ORDER BY id"
        )
        for row in c.execute(sql):
            tasks.append({
                "id": row[0],
                "question": row[1] or "",
                "options": row[2] or "",
                "correct_answer": row[3] or "",
                "hint": row[4] or "",
            })
    return tasks


def get_task_by_id(task_id: int) -> dict | None:
    with sqlite3.connect(TESTS_DB_EGE) as conn:
        c = conn.cursor()
        _ensure_tests_bug(conn)
        ans_col = _detect_answer_column(conn, "tests_bug")
        sql = (
            f"SELECT id, question, options, COALESCE({ans_col},''), COALESCE(hint,'') FROM tests_bug WHERE id=?"
        )
        c.execute(sql, (int(task_id),))
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
    with sqlite3.connect(TESTS_DB_EGE) as conn:
        c = conn.cursor()
        _ensure_tests_bug(conn)
        col = field
        if field == "correct_answer":
            col = _detect_answer_column(conn, "tests_bug")
        c.execute(f"UPDATE tests_bug SET {col}=? WHERE id=?", (new_text, int(task_id)))
        conn.commit()


def unhide_task(task_id: int) -> None:
    # Применяем накопленные правки из tests_bug -> tests и снимаем флаг has_issue
    with sqlite3.connect(TESTS_DB_EGE) as conn:
        c = conn.cursor()
        _ensure_tests_bug(conn)
        # Определим имя колонки с правильным ответом в обеих таблицах
        ans_bug = _detect_answer_column(conn, "tests_bug")
        ans_tests = _detect_answer_column(conn, "tests")
        # Обновляем основную таблицу из тестовой (только редактируемые поля)
        c.execute(
            f"""
            UPDATE tests
            SET question=(SELECT question FROM tests_bug WHERE id=?),
                options=(SELECT options FROM tests_bug WHERE id=?),
                {ans_tests}=(SELECT {ans_bug} FROM tests_bug WHERE id=?),
                hint=(SELECT hint FROM tests_bug WHERE id=?)
            WHERE id=?
            """,
            (int(task_id), int(task_id), int(task_id), int(task_id), int(task_id)),
        )
        # Снимаем флаг скрытия
        try:
            c.execute("UPDATE tests SET has_issue=0 WHERE id=?", (int(task_id),))
        except Exception:
            pass
        # Можно удалить запись из tests_bug (чтобы в списке не висела)
        try:
            c.execute("DELETE FROM tests_bug WHERE id=?", (int(task_id),))
        except Exception:
            pass
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

