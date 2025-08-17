import os
import sqlite3
from datetime import datetime
from typing import Optional, Iterable


def _normalize(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = str(value).strip()
    return value if value else None


def _safe_distinct_user_ids(conn: sqlite3.Connection) -> list[int]:
    """Собираем уникальные user_id из test_answers, test_activity, test_progress (если есть)."""
    user_ids: set[int] = set()
    cur = conn.cursor()

    def collect(sql: str) -> None:
        try:
            cur.execute(sql)
            for (uid,) in cur.fetchall():
                try:
                    user_ids.add(int(uid))
                except Exception:
                    pass
        except sqlite3.OperationalError as e:
            if "no such table" in str(e).lower():
                return
            raise

    collect("SELECT DISTINCT user_id FROM test_answers")
    collect("SELECT DISTINCT user_id FROM test_activity")
    collect("SELECT DISTINCT user_id FROM test_progress")
    return sorted(user_ids)


def _latest_non_empty(conn: sqlite3.Connection, user_id: int, column: str) -> Optional[str]:
    """Берём последнее непустое значение столбца из test_answers для пользователя."""
    cur = conn.cursor()
    # Учитываем возможные пустые/NULL значения и разные форматы времени
    cur.execute(
        f"""
        SELECT {column}
        FROM test_answers
        WHERE user_id = ? AND TRIM(COALESCE({column}, '')) <> ''
        ORDER BY
          CASE WHEN TRIM(COALESCE(answer_time, '')) <> '' THEN answer_time ELSE NULL END DESC,
          id DESC
        LIMIT 1
        """,
        (user_id,),
    )
    row = cur.fetchone()
    return _normalize(row[0]) if row else None


def _first_answer_time(conn: sqlite3.Connection, user_id: int) -> Optional[str]:
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT MIN(answer_time)
            FROM test_answers
            WHERE user_id = ? AND TRIM(COALESCE(answer_time, '')) <> ''
            """,
            (user_id,),
        )
        row = cur.fetchone()
        return _normalize(row[0]) if row else None
    except sqlite3.OperationalError:
        return None


def ensure_user_profiles_table(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS user_profiles (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            created_at TEXT
        )
        """
    )
    conn.commit()


def upsert_user_profile(conn: sqlite3.Connection, user_id: int, username: Optional[str], full_name: Optional[str], created_at: Optional[str]) -> None:
    """Обновляем профиль: не затираем уже заполненные поля пустыми значениями."""
    username = _normalize(username)
    full_name = _normalize(full_name)
    created_at = _normalize(created_at)

    cur = conn.cursor()
    cur.execute("SELECT username, full_name, created_at FROM user_profiles WHERE user_id=?", (user_id,))
    existing = cur.fetchone()
    if existing:
        ex_username, ex_full_name, ex_created_at = existing
        username = username or _normalize(ex_username)
        full_name = full_name or _normalize(ex_full_name)
        # Не трогаем created_at, если он уже есть. Иначе — ставим самое раннее известное/текущее
        created_at = _normalize(ex_created_at) or created_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    else:
        created_at = created_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cur.execute(
        """
        INSERT INTO user_profiles (user_id, username, full_name, created_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username = excluded.username,
            full_name = excluded.full_name,
            created_at = COALESCE(user_profiles.created_at, excluded.created_at)
        """,
        (user_id, username, full_name, created_at),
    )
    conn.commit()


def backfill(db_path: str) -> None:
    with sqlite3.connect(db_path) as conn:
        ensure_user_profiles_table(conn)

        user_ids = _safe_distinct_user_ids(conn)
        print(f"[backfill] Found {len(user_ids)} unique users to process")

        for uid in user_ids:
            username = _latest_non_empty(conn, uid, "username")
            full_name = _latest_non_empty(conn, uid, "full_name")
            first_seen = _first_answer_time(conn, uid)
            upsert_user_profile(conn, uid, username, full_name, first_seen)

        print("[backfill] Done")


if __name__ == "__main__":
    # По умолчанию используем shared/test_answers.db рядом со скриптом
    this_dir = os.path.dirname(os.path.abspath(__file__))
    default_db = os.path.join(this_dir, "test_answers.db")
    db_path = os.getenv("DB_PATH", default_db)
    print(f"[backfill] DB: {db_path}")
    backfill(db_path)


