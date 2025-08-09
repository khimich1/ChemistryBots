import sqlite3
from config import DB_PATH, TESTS_DB_PATH

def get_last_activity_rows(limit=50):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("""
            SELECT user_id, test_type, question_id, started_at, answered_at, is_correct
            FROM test_activity
            ORDER BY started_at DESC
            LIMIT ?
        """, (limit,))
        return c.fetchall()

def get_current_task(user_id):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("""
            SELECT test_type, question_id, started_at
            FROM test_activity
            WHERE user_id=? AND answered_at IS NULL
            ORDER BY started_at DESC
            LIMIT 1
        """, (user_id,))
        return c.fetchone()

def get_online_students(timeout_minutes=10):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("""
            SELECT user_id, MAX(started_at)
            FROM test_activity
            GROUP BY user_id
        """)
        rows = c.fetchall()
    from datetime import datetime, timedelta
    now = datetime.now()
    online = []
    for uid, last_start in rows:
        try:
            last_dt = datetime.strptime(last_start, "%Y-%m-%d %H:%M:%S")
        except Exception:
            continue
        if now - last_dt <= timedelta(minutes=timeout_minutes):
            online.append({"user_id": uid, "last_start": last_start})
    return online

def get_session_activity(user_id, since_ts):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("""
            SELECT test_type, question_id, started_at, answered_at, user_answer, is_correct
            FROM test_activity
            WHERE user_id=? AND started_at >= ?
            ORDER BY started_at
        """, (user_id, since_ts))
        return c.fetchall()

def get_question_details(q_id):
    if not TESTS_DB_PATH:
        return None
    with sqlite3.connect(TESTS_DB_PATH) as conn:
        c = conn.cursor()
        c.execute("""
            SELECT id, question, options, correct_answer
            FROM tests
            WHERE id=?
        """, (q_id,))
        row = c.fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "question": row[1] or "",
            "options": row[2] or "",
            "correct_answer": str(row[3] or "").strip()
        }
