import sqlite3
import re
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any, Tuple

from config import DB_PATH, TESTS_DB_PATH  # DB_PATH -> test_answers.db, TESTS_DB_PATH -> tests1.db


def _safe_fetchone(conn: sqlite3.Connection, sql: str, params=()) -> Optional[tuple]:
    cur = conn.cursor
    cur = conn.cursor()
    try:
        cur.execute(sql, params)
        return cur.fetchone()
    except sqlite3.OperationalError as e:
        if "no such table" in str(e).lower():
            return None
        raise


def _safe_fetchall(conn: sqlite3.Connection, sql: str, params=()) -> List[tuple]:
    cur = conn.cursor()
    try:
        cur.execute(sql, params)
        return cur.fetchall()
    except sqlite3.OperationalError as e:
        if "no such table" in str(e).lower():
            return []
        raise


def _pick_column(conn: sqlite3.Connection, table: str, candidates: List[str]) -> Optional[str]:
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    cols = {row[1].lower() for row in cur.fetchall()}
    for name in candidates:
        if name.lower() in cols:
            return name
    return None


# =========================
# DB_PATH (test_answers.db): test_activity, test_answers, test_progress
# TESTS_DB_PATH (tests1.db): tests (question, options, <correct*>)
# =========================

def get_online_students(timeout_minutes: int = 10, with_names: bool = False) -> List[Dict[str, Any]]:
    now = datetime.now()
    out: List[Dict[str, Any]] = []
    with sqlite3.connect(DB_PATH) as conn:
        rows = _safe_fetchall(
            conn,
            "SELECT user_id, MAX(started_at) AS last_start FROM test_activity GROUP BY user_id"
        )
        for uid, last_start in rows:
            try:
                last_dt = datetime.strptime(str(last_start), "%Y-%m-%d %H:%M:%S")
            except Exception:
                continue
            if now - last_dt > timedelta(minutes=timeout_minutes):
                continue

            username = None
            if with_names:
                row = _safe_fetchone(
                    conn,
                    "SELECT username FROM test_answers WHERE user_id=? ORDER BY answer_time DESC LIMIT 1",
                    (uid,)
                )
                if row:
                    username = row[0] or None

            out.append({"user_id": uid, "username": username, "full_name": None, "last_start": str(last_start)})
    return out


def get_current_task(user_id: int) -> Optional[tuple]:
    """(test_type, question_id, started_at) незавершённого вопроса."""
    with sqlite3.connect(DB_PATH) as conn:
        row = _safe_fetchone(
            conn,
            """
            SELECT test_type, question_id, started_at
            FROM test_activity
            WHERE user_id = ? AND (answered_at IS NULL OR TRIM(answered_at) = '')
            ORDER BY started_at DESC
            LIMIT 1
            """,
            (user_id,)
        )
    return row


def get_session_activity(user_id: int, since_ts: str, with_names: bool = False) -> List[Dict[str, Any]]:
    with sqlite3.connect(DB_PATH) as conn:
        rows = _safe_fetchall(
            conn,
            """
            SELECT test_type, question_id, started_at, answered_at, user_answer, is_correct
            FROM test_activity
            WHERE user_id = ? AND started_at >= ?
            ORDER BY started_at
            """,
            (user_id, since_ts)
        )
    return [
        {
            "test_type": t, "question_id": q, "started_at": s,
            "answered_at": a, "user_answer": ua, "is_correct": ic
        } for t, q, s, a, ua, ic in rows
    ]


def get_recent_activity(user_id: int, limit: int = 20) -> List[Dict[str, Any]]:
    """Последние N событий пользователя (если практика не запущена)."""
    with sqlite3.connect(DB_PATH) as conn:
        rows = _safe_fetchall(
            conn,
            """
            SELECT test_type, question_id, started_at, answered_at, user_answer, is_correct
            FROM test_activity
            WHERE user_id = ?
            ORDER BY COALESCE(answered_at, started_at) DESC, started_at DESC
            LIMIT ?
            """,
            (user_id, limit)
        )
    return [
        {
            "test_type": t, "question_id": q, "started_at": s,
            "answered_at": a, "user_answer": ua, "is_correct": ic
        } for t, q, s, a, ua, ic in rows
    ]


def get_question_details(question_id: int) -> Dict[str, Any]:
    """
    Достаём вопрос из tests1.db (таблица tests).
    Колонки подбираем автоматически:
      question: ['question','question_text','text','q_text']
      options:  ['options','variants','choices','answers']
      correct:  ['correct_ans','correct_answer','correct','right_answer','answer']
      type:     ['type','test_type','theme','task_type']
    """
    with sqlite3.connect(TESTS_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        q_col = _pick_column(conn, "tests", ["question", "question_text", "text", "q_text"])
        o_col = _pick_column(conn, "tests", ["options", "variants", "choices", "answers"])
        c_col = _pick_column(conn, "tests", ["correct_ans", "correct_answer", "correct", "right_answer", "answer"])
        t_col = _pick_column(conn, "tests", ["type", "test_type", "theme", "task_type"])
        if not q_col:
            return {}
        fields = [f"{q_col} AS question"]
        if o_col:
            fields.append(f"{o_col} AS options")
        if c_col:
            fields.append(f"{c_col} AS correct_answer")
        if t_col:
            fields.append(f"{t_col} AS type")
        sql = f"SELECT {', '.join(fields)} FROM tests WHERE id = ?"
        cur = conn.cursor()
        try:
            cur.execute(sql, (question_id,))
            row = cur.fetchone()
        except sqlite3.OperationalError:
            return {}
    if not row:
        return {}
    return {
        "question": row["question"] if "question" in row.keys() else "",
        "options": row["options"] if "options" in row.keys() else "",
        "correct_answer": row["correct_answer"] if "correct_answer" in row.keys() else "",
        "type": row["type"] if "type" in row.keys() else None,
    }


def _parse_id_list(ids_string: str) -> List[int]:
    parts = [p for p in re.split(r"[,\s]+", ids_string or "") if p.strip()]
    out = []
    for p in parts:
        try:
            out.append(int(p))
        except ValueError:
            pass
    return out


def get_question_position(user_id: int, test_type: int, question_id: int) -> Tuple[Optional[int], Optional[int]]:
    """
    По test_progress определяем позицию вопроса в тесте: (номер_вопроса, всего_вопросов).
    Ничего в БД не меняем.
    """
    with sqlite3.connect(DB_PATH) as conn:
        row = _safe_fetchone(
            conn,
            """
            SELECT q_ids
            FROM test_progress
            WHERE user_id = ? AND test_type = ?
            ORDER BY ROWID DESC
            LIMIT 1
            """,
            (user_id, test_type)
        )
    if not row or not row[0]:
        return None, None

    ids = _parse_id_list(row[0])
    total = len(ids) if ids else None
    pos = None
    if ids and question_id in ids:
        pos = ids.index(int(question_id)) + 1
    return pos, total
