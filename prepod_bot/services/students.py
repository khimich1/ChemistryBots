import sqlite3
from datetime import datetime, timedelta
from config import DB_PATH


def get_online_students(timeout_minutes=10, with_names=False):
    """
    Возвращает список учеников, которые были активны в последние timeout_minutes минут.
    Если with_names=True, подгружает username и full_name из таблицы users.
    """
    now = datetime.now()
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        if with_names:
            c.execute("""
                SELECT ta.user_id, u.username, u.full_name, MAX(ta.started_at)
                FROM test_activity ta
                LEFT JOIN users u ON ta.user_id = u.user_id
                GROUP BY ta.user_id
            """)
        else:
            c.execute("""
                SELECT user_id, MAX(started_at)
                FROM test_activity
                GROUP BY user_id
            """)
        rows = c.fetchall()

    online = []
    for row in rows:
        if with_names:
            uid, username, full_name, last_start = row
        else:
            uid, last_start = row
            username, full_name = None, None

        try:
            last_dt = datetime.strptime(last_start, "%Y-%m-%d %H:%M:%S")
        except Exception:
            continue

        if now - last_dt <= timedelta(minutes=timeout_minutes):
            online.append({
                "user_id": uid,
                "username": username,
                "full_name": full_name,
                "last_start": last_start
            })
    return online


def get_session_activity(user_id, since_ts, with_names=False):
    """
    Возвращает список событий за сессию начиная с since_ts.
    Если with_names=True, подгружает username и full_name.
    """
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        if with_names:
            c.execute("""
                SELECT ta.test_type, ta.question_id, ta.started_at, ta.answered_at,
                       ta.user_answer, ta.is_correct, u.username, u.full_name
                FROM test_activity ta
                LEFT JOIN users u ON ta.user_id = u.user_id
                WHERE ta.user_id = ? AND ta.started_at >= ?
                ORDER BY ta.started_at
            """, (user_id, since_ts))
        else:
            c.execute("""
                SELECT test_type, question_id, started_at, answered_at,
                       user_answer, is_correct
                FROM test_activity
                WHERE user_id = ? AND started_at >= ?
                ORDER BY started_at
            """, (user_id, since_ts))
        rows = c.fetchall()

    events = []
    for row in rows:
        if with_names:
            test_type, q_id, started_at, answered_at, user_answer, is_correct, username, full_name = row
        else:
            test_type, q_id, started_at, answered_at, user_answer, is_correct = row
            username, full_name = None, None

        events.append({
            "test_type": test_type,
            "question_id": q_id,
            "started_at": started_at,
            "answered_at": answered_at,
            "user_answer": user_answer,
            "is_correct": is_correct,
            "username": username,
            "full_name": full_name
        })
    return events


def get_current_task(user_id):
    """
    Возвращает текущий вопрос (test_type, question_id, started_at) для ученика.
    Если вопроса нет — возвращает None.
    """
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("""
            SELECT test_type, question_id, started_at
            FROM test_activity
            WHERE user_id = ? AND answered_at IS NULL
            ORDER BY started_at DESC
            LIMIT 1
        """, (user_id,))
        row = c.fetchone()
    return row


def get_question_details(question_id):
    """
    Возвращает текст вопроса, варианты и правильный ответ по ID вопроса.
    """
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("""
            SELECT question, options, correct_answer
            FROM questions
            WHERE id = ?
        """, (question_id,))
        row = c.fetchone()
    if row:
        return {"question": row[0], "options": row[1], "correct_answer": row[2]}
    return {}
