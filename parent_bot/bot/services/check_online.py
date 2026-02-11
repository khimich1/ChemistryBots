import os
import sqlite3
from datetime import datetime, timedelta

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "..", "shared", "test_answers.db")

def check_online():
    now = datetime.now()
    timeout_minutes = 30

    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("""
            SELECT id, user_id, test_type, question_id, started_at, answered_at
            FROM test_activity
            WHERE answered_at IS NULL
        """)
        rows = c.fetchall()

        print(f"Всего найдено строк с answered_at IS NULL: {len(rows)}\n")
        for row in rows:
            user_id = row[1]
            started_at = row[4]
            if started_at:
                t1 = datetime.strptime(started_at, "%Y-%m-%d %H:%M:%S")
                delta = now - t1
                print(f"Пользователь ID: {user_id}, started_at: {started_at}, прошло минут: {delta.total_seconds() // 60}")
                if delta.total_seconds() < timeout_minutes * 60:
                    print("-> Этот пользователь считается онлайн.")
                else:
                    print("-> Этот пользователь уже не онлайн.")
            else:
                print("Нет значения started_at!")

check_online()
