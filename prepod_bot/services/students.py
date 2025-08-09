import sqlite3
from datetime import datetime
from config import DB_PATH

def get_online_students(timeout_minutes=10):
    """
    Возвращает список учеников, которые что-либо делали за последние timeout_minutes минут.
    (username не используется)
    """
    now = datetime.now()
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        # Теперь не выбираем username!
        c.execute("""
            SELECT user_id, MAX(started_at)
            FROM test_activity
            GROUP BY user_id
        """)
        rows = c.fetchall()
        results = []
        for user_id, last_started in rows:
            if last_started:
                try:
                    t1 = datetime.strptime(last_started, "%Y-%m-%d %H:%M:%S")
                    delta = now - t1
                    if delta.total_seconds() < timeout_minutes * 60:
                        results.append({
                            "user_id": user_id,
                            "started_at": last_started
                        })
                except Exception as e:
                    print("Ошибка парсинга даты started_at:", last_started, e)
        return results

