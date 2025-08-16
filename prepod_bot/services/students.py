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


def _latest_identity_row(conn: sqlite3.Connection, user_id: int) -> Optional[tuple]:
    """
    Возвращает кортеж (full_name, username) из последнего ответа пользователя.
    Пустые строки приводим к NULL на уровне SQL.
    """
    return _safe_fetchone(
        conn,
        """
        SELECT
            NULLIF(TRIM(full_name), '') AS full_name,
            NULLIF(TRIM(username), '')  AS username
        FROM test_answers
        WHERE user_id = ?
        ORDER BY
          CASE WHEN TRIM(COALESCE(answer_time, '')) <> '' THEN answer_time ELSE NULL END DESC,
          id DESC
        LIMIT 1
        """,
        (user_id,),
    )


def get_all_students() -> List[Dict[str, Any]]:
    """
    Собирает список всех уникальных учеников из БД `test_answers.db`.
    Правило имени: full_name → username → str(user_id).
    Возвращает список словарей: {user_id, full_name, username, label}.
    """
    results: List[Dict[str, Any]] = []
    with sqlite3.connect(DB_PATH) as conn:
        # Собираем всех из ответов и профилей
        ids_set: set[int] = set()
        for (uid,) in _safe_fetchall(conn, "SELECT DISTINCT user_id FROM test_answers"):
            try:
                ids_set.add(int(uid))
            except Exception:
                pass
        for (uid,) in _safe_fetchall(conn, "SELECT user_id FROM user_profiles"):
            try:
                ids_set.add(int(uid))
            except Exception:
                pass

        for user_id in sorted(ids_set):
            # Пропускаем скрытых
            if _is_hidden(conn, user_id):
                continue
            # Имя: user_profiles → последний ответ
            full_name, username = get_identity(conn, user_id)
            if not (full_name or username):
                row = _latest_identity_row(conn, user_id) or (None, None)
                full_name, username = row
            label = (full_name or username or f"ID {user_id}")
            results.append({
                "user_id": user_id,
                "full_name": full_name,
                "username": username,
                "label": label,
            })
    # Сортируем по label для стабильности отображения
    results.sort(key=lambda s: str(s.get("label") or ""))
    return results


def _ensure_user_profiles(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS user_profiles (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            created_at TEXT,
            hide_reason TEXT
        )
        """
    )
    # Миграция: добавляем столбец hide_reason, если его нет
    cur.execute("PRAGMA table_info(user_profiles)")
    cols = {row[1] for row in cur.fetchall()}
    if "hide_reason" not in cols:
        cur.execute("ALTER TABLE user_profiles ADD COLUMN hide_reason TEXT")
    conn.commit()


def get_identity(conn: sqlite3.Connection, user_id: int) -> Tuple[Optional[str], Optional[str]]:
    """
    Возвращает (full_name, username) с приоритетом user_profiles → test_answers.
    """
    _ensure_user_profiles(conn)
    row = _safe_fetchone(
        conn,
        "SELECT NULLIF(TRIM(full_name), ''), NULLIF(TRIM(username), '') FROM user_profiles WHERE user_id=?",
        (user_id,),
    )
    if row and (row[0] or row[1]):
        return row[0], row[1]
    latest = _latest_identity_row(conn, user_id) or (None, None)
    return latest[0], latest[1]


def update_user_profile(user_id: int, *, username: Optional[str] = None, full_name: Optional[str] = None) -> None:
    """
    Обновляет профиль пользователя в user_profiles. Если записи нет — создаёт.
    Пустые строки трактуются как NULL (очистка поля).
    """
    username = (username or "").strip()
    full_name = (full_name or "").strip()
    username_val = username if username else None
    full_name_val = full_name if full_name else None
    with sqlite3.connect(DB_PATH) as conn:
        _ensure_user_profiles(conn)
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM user_profiles WHERE user_id=?", (user_id,))
        exists = cur.fetchone() is not None
        if exists:
            if username is not None:
                cur.execute("UPDATE user_profiles SET username=? WHERE user_id=?", (username_val, user_id))
            if full_name is not None:
                cur.execute("UPDATE user_profiles SET full_name=? WHERE user_id=?", (full_name_val, user_id))
        else:
            cur.execute(
                """
                INSERT INTO user_profiles (user_id, username, full_name, created_at)
                VALUES (?, ?, ?, datetime('now','localtime'))
                """,
                (user_id, username_val, full_name_val),
            )
        conn.commit()


def _is_hidden(conn: sqlite3.Connection, user_id: int) -> bool:
    _ensure_user_profiles(conn)
    row = _safe_fetchone(
        conn,
        "SELECT NULLIF(TRIM(hide_reason), '') FROM user_profiles WHERE user_id=?",
        (user_id,),
    )
    return bool(row and row[0])


def clear_hide_reason_all() -> int:
    """Очищает поле hide_reason у всех пользователей. Возвращает число изменённых строк."""
    with sqlite3.connect(DB_PATH) as conn:
        _ensure_user_profiles(conn)
        cur = conn.cursor()
        cur.execute("UPDATE user_profiles SET hide_reason=NULL WHERE TRIM(COALESCE(hide_reason, '')) <> ''")
        conn.commit()
        return cur.rowcount or 0


def set_hide_reason(user_id: int, reason: Optional[str]) -> None:
    """Устанавливает причину скрытия (или очищает при reason=None)."""
    with sqlite3.connect(DB_PATH) as conn:
        _ensure_user_profiles(conn)
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM user_profiles WHERE user_id=?", (user_id,))
        exists = cur.fetchone() is not None
        if exists:
            cur.execute("UPDATE user_profiles SET hide_reason=? WHERE user_id=?", (reason, user_id))
        else:
            cur.execute(
                """
                INSERT INTO user_profiles (user_id, hide_reason, created_at)
                VALUES (?, ?, datetime('now','localtime'))
                """,
                (user_id, reason),
            )
        conn.commit()
