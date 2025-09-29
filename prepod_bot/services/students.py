import sqlite3
import os
import re
from datetime import datetime, timedelta
from html import escape
from typing import Optional, Dict, List, Any, Tuple

from config import DB_PATH, TESTS_DB_EGE, TESTS_DB_OGE  # test DBs: EGE and OGE


def _safe_fetchone(conn: sqlite3.Connection, sql: str, params=()) -> Optional[tuple]:
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
# TESTS_DB_EGE / TESTS_DB_OGE: tests (question, options, <correct*>)
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


def _fetch_question_from_db(db_path: str, question_id: int) -> Dict[str, Any]:
    """
    Универсальный извлекатель вопроса из БД с таблицей tests, где
    названия колонок могут отличаться. Возвращает пустой словарь если не найдено.
    """
    with sqlite3.connect(db_path) as conn:
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


def get_question_details(question_id: int) -> Dict[str, Any]:
    """
    Достаём вопрос сначала из EGE, если нет — пробуем OGE.
    Колонки подбираем автоматически:
      question: ['question','question_text','text','q_text']
      options:  ['options','variants','choices','answers']
      correct:  ['correct_ans','correct_answer','correct','right_answer','answer']
      type:     ['type','test_type','theme','task_type']
    """
    # 1) EGE
    res = _fetch_question_from_db(TESTS_DB_EGE, question_id)
    if res:
        return res
    # 2) OGE
    return _fetch_question_from_db(TESTS_DB_OGE, question_id)


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


# =========================
# Новые утилиты для оповещений преподавателя
# =========================

def get_activity_updates_since(since_ts: str) -> List[Dict[str, Any]]:
    """
    Возвращает список событий из test_activity, произошедших строго ПОСЛЕ since_ts.
    Учитываем как старт вопроса (started_at), так и ответ (answered_at).
    """
    with sqlite3.connect(DB_PATH) as conn:
        rows = _safe_fetchall(
            conn,
            """
            SELECT user_id, test_type, question_id, started_at, answered_at, user_answer, is_correct
            FROM test_activity
            WHERE (COALESCE(started_at, '') > ?)
               OR (TRIM(COALESCE(answered_at, '')) <> '' AND answered_at > ?)
            ORDER BY COALESCE(answered_at, started_at)
            """,
            (since_ts, since_ts)
        )
    out: List[Dict[str, Any]] = []
    for user_id, t, q, s, a, ua, ic in rows:
        out.append({
            "user_id": user_id,
            "test_type": t,
            "question_id": q,
            "started_at": s,
            "answered_at": a,
            "user_answer": ua,
            "is_correct": ic,
        })
    return out


def get_user_label(user_id: int) -> str:
    """
    Удобная подпись ученика: full_name → username → ID.
    """
    with sqlite3.connect(DB_PATH) as conn:
        full_name, username = get_identity(conn, user_id)
        return (full_name or username or f"ID {user_id}")


# =========================
# Сводка по успеваемости ученика (для преподавателя)
# =========================

# Кэш наличия id в базах ЕГЭ/ОГЭ, чтобы не дергать БД слишком часто
_CACHE_EGE: dict[int, bool] = {}
_CACHE_OGE: dict[int, bool] = {}
_ANS_CACHE_EGE: dict[int, str] = {}
_ANS_CACHE_OGE: dict[int, str] = {}

def _exists_in_tests(db_path: str, cache: dict[int, bool], question_id: int) -> bool:
    if question_id in cache:
        return cache[question_id]
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM tests WHERE id=? LIMIT 1", (question_id,))
            row = cur.fetchone()
            ok = row is not None
            cache[question_id] = ok
            return ok
    except Exception:
        cache[question_id] = False
        return False

def _get_correct_answer_from_tests(db_path: str, cache: dict[int, str], question_id: int) -> str | None:
    """Возвращает нормализованный правильный ответ из таблицы tests по id вопроса."""
    if question_id in cache:
        return cache[question_id]
    try:
        with sqlite3.connect(db_path) as c:
            cur = c.cursor()
            cur.execute("PRAGMA table_info(tests)")
            cols = {row[1].lower(): row[1] for row in cur.fetchall()}
            corr_col = None
            for cand in ["correct_ans", "correct_answer", "correct", "right_answer", "answer"]:
                if cand in cols:
                    corr_col = cols[cand]
                    break
            if not corr_col:
                cache[question_id] = ""
                return ""
            cur.execute(f"SELECT {corr_col} FROM tests WHERE id=?", (question_id,))
            row = cur.fetchone()
            ans = (row[0] if row else "")
            ans_norm = str(ans).strip().lower()
            cache[question_id] = ans_norm
            return ans_norm
    except Exception:
        cache[question_id] = ""
        return ""

def get_exam_answer_stats(user_id: int, exam: str) -> tuple[int, int]:
    """Возвращает (correct, total) по ответам экзамена (ege|oge) из test_answers с проверкой по базе тестов."""
    exam = (exam or "").lower().strip()
    if exam not in {"ege", "oge"}:
        exam = "ege"

    with sqlite3.connect(DB_PATH) as conn:
        rows = _safe_fetchall(
            conn,
            """
            SELECT test_type, question_id, correct_answer,
                   CASE WHEN CAST(is_correct AS INTEGER)=1 THEN 1 ELSE 0 END AS is_correct
            FROM test_answers
            WHERE user_id=?
            """,
            (user_id,)
        )

    total = 0
    correct = 0
    for t_type, qid, corr_ans, is_corr in rows:
        try:
            t = int(t_type or 0)
            q = int(qid)
        except Exception:
            continue

        if exam == "ege":
            if not (1 <= t <= 28):
                continue
            right = _get_correct_answer_from_tests(TESTS_DB_EGE, _ANS_CACHE_EGE, q)
        else:
            if not (1 <= t <= 19):
                continue
            right = _get_correct_answer_from_tests(TESTS_DB_OGE, _ANS_CACHE_OGE, q)

        if right is None:
            continue
        if str(corr_ans or "").strip().lower() != right:
            continue

        total += 1
        correct += int(is_corr or 0)

    return int(correct), int(total)


def _get_assigned_question_ids(user_id: int) -> tuple[set[int], set[int]]:
    """
    Возвращает два множества ID вопросов, назначенных ученику через group_tasks:
      (ege_ids, oge_ids)

    Связка:
      work_groups (user_id -> group_no)
      group_tasks (group_no -> items: "ege:ID, oge:ID, ...")
    """
    ege_ids: set[int] = set()
    oge_ids: set[int] = set()
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            # Найдём все рабочие группы пользователя
            try:
                cur.execute(
                    "SELECT group_no FROM work_groups WHERE user_id=?",
                    (int(user_id),),
                )
                groups = [int(r[0]) for r in cur.fetchall()]
            except sqlite3.OperationalError:
                groups = []
            if not groups:
                return ege_ids, oge_ids

            # Соберём все items по этим группам
            placeholders = ",".join(["?"] * len(groups))
            try:
                cur.execute(
                    f"SELECT items FROM group_tasks WHERE group_no IN ({placeholders})",
                    [int(g) for g in groups],
                )
                rows = [str(r[0] or "") for r in cur.fetchall()]
            except sqlite3.OperationalError:
                rows = []

        # Разберём items формата "ege:1, oge:3, ege:5"
        for items in rows:
            parts = [p.strip() for p in items.split(",") if p.strip()]
            for part in parts:
                try:
                    exam_code, sid = part.split(":", 1)
                    qid = int(str(sid).strip())
                    exam_code = str(exam_code or "").strip().lower()
                except Exception:
                    continue
                if exam_code == "oge":
                    oge_ids.add(qid)
                else:
                    # по умолчанию считаем как ege
                    ege_ids.add(qid)
    except Exception:
        # В случае любой ошибки возвращаем пустые множества — UI покажет 0/0
        return set(), set()

    return ege_ids, oge_ids


def get_assigned_exam_stats(user_id: int) -> dict[str, tuple[int, int]]:
    """
    Подсчитывает статистику по НАЗНАЧЕННЫМ вопросам для ЕГЭ и ОГЭ.
    Возвращает словарь { 'ege': (correct, total), 'oge': (correct, total) }.

    Логика подсчёта «верных» — по последнему ответу на каждый назначенный вопрос.
    """
    ege_ids, oge_ids = _get_assigned_question_ids(int(user_id))

    def _count_for(ids: set[int]) -> tuple[int, int]:
        if not ids:
            return 0, 0
        last: dict[int, int | None] = {int(q): None for q in ids}
        try:
            with sqlite3.connect(DB_PATH) as conn:
                cur = conn.cursor()
                placeholders = ",".join(["?"] * len(ids))
                params = [int(user_id), *[int(q) for q in ids]]
                cur.execute(
                    f"""
                    SELECT question_id, is_correct, id
                    FROM test_answers
                    WHERE user_id=? AND question_id IN ({placeholders})
                    ORDER BY id
                    """,
                    params,
                )
                for qid, is_corr, _rid in cur.fetchall():
                    if int(qid) in last:
                        last[int(qid)] = None if is_corr is None else int(is_corr)
        except sqlite3.OperationalError:
            pass
        correct = sum(1 for v in last.values() if v == 1)
        total = len(ids)
        return int(correct), int(total)

    ege_correct, ege_total = _count_for(ege_ids)
    oge_correct, oge_total = _count_for(oge_ids)
    return {
        "ege": (ege_correct, ege_total),
        "oge": (oge_correct, oge_total),
    }


def get_overall_exam_stats_fixed(user_id: int) -> dict[str, tuple[int, int]]:
    """
    Возвращает прогресс по ВСЕЙ базе экзамена, с фиксированными знаменателями:
      - ЕГЭ: 840 (28 типов × 30 заданий)
      - ОГЭ: 570 (19 типов × 30 заданий)

    Числитель — количество УНИКАЛЬНЫХ вопросов, на которые ученик ответил верно
    хотя бы раз (по данным test_answers), и которые принадлежат выбранному экзамену
    (проверяем по диапазону test_type и по совпадению correct_answer с эталоном из БД тестов).
    """

    def _unique_correct(exam: str) -> int:
        exam_norm = (exam or "").strip().lower()
        if exam_norm not in {"ege", "oge"}:
            exam_norm = "ege"
        unique_qids: set[int] = set()
        with sqlite3.connect(DB_PATH) as conn:
            rows = _safe_fetchall(
                conn,
                """
                SELECT test_type, question_id, correct_answer,
                       CASE WHEN CAST(is_correct AS INTEGER)=1 THEN 1 ELSE 0 END AS is_correct
                FROM test_answers
                WHERE user_id=?
                """,
                (user_id,)
            )
        for t_type, qid, corr_ans, is_corr in rows:
            try:
                t = int(t_type or 0)
                q = int(qid)
            except Exception:
                continue
            # Принадлежность экзамену и проверка эталона
            if exam_norm == "ege":
                if not (1 <= t <= 28):
                    continue
                right = _get_correct_answer_from_tests(TESTS_DB_EGE, _ANS_CACHE_EGE, q)
            else:
                if not (1 <= t <= 19):
                    continue
                right = _get_correct_answer_from_tests(TESTS_DB_OGE, _ANS_CACHE_OGE, q)
            if right is None:
                continue
            if str(corr_ans or "").strip().lower() != right:
                continue
            if int(is_corr or 0) == 1:
                unique_qids.add(q)
        return int(len(unique_qids))

    ege_correct = _unique_correct("ege")
    oge_correct = _unique_correct("oge")

    # Фиксированные знаменатели
    ege_total = 840
    oge_total = 570
    return {
        "ege": (min(ege_correct, ege_total), ege_total),
        "oge": (min(oge_correct, oge_total), oge_total),
    }

def build_user_summary_text(user_id: int) -> str:
    """
    Короткая сводка из 4 прогресс-баров:
      - ЕГЭ тесты
      - ОГЭ тесты
      - Карточки
      - Зачёт по учебнику
    """
    with sqlite3.connect(DB_PATH) as conn:
        full_name, username = get_identity(conn, user_id)
        label = (full_name or username or f"ID {user_id}")

    # ЕГЭ/ОГЭ — прогресс по ВСЕЙ базе с фиксированными знаменателями (840/570)
    overall = get_overall_exam_stats_fixed(user_id)
    ege_correct, ege_total = overall.get("ege", (0, 0))
    oge_correct, oge_total = overall.get("oge", (0, 0))

    # Карточки: считаем из общего числа карточек в базе (shared/ege_chemistry_substances.sqlite),
    # а в числителе — число УНИКАЛЬНЫХ карточек, на которые ученик ответил верно хотя бы раз.
    def _count_total_cards() -> int:
        try:
            # shared/ege_chemistry_substances.sqlite относительно репозитория
            repo_root = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
            db_path = os.path.join(repo_root, "shared", "ege_chemistry_substances.sqlite")
            if not os.path.exists(db_path):
                return 0
            total_cards = 0
            with sqlite3.connect(db_path) as c:
                cur = c.cursor()
                cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = [r[0] for r in cur.fetchall()]
                for tbl in tables:
                    # Пытаемся подобрать имена колонок формул/названий
                    cur.execute(f"PRAGMA table_info({tbl})")
                    cols = {row[1].lower(): row[1] for row in cur.fetchall()}
                    f_col = None
                    i_col = None
                    t_col = None
                    for cand in ("formula", "формула"):
                        if cand in cols:
                            f_col = cols[cand]
                            break
                    for cand in ("iupac", "номенк"):
                        if cand in cols:
                            i_col = cols[cand]
                            break
                    for cand in ("trivial", "тривиал", "синоним"):
                        if cand in cols:
                            t_col = cols[cand]
                            break
                    # Строим условие: хотя бы одно поле непустое
                    exprs: list[str] = []
                    if f_col:
                        exprs.append(f"TRIM(COALESCE({f_col}, '')) <> ''")
                    if i_col:
                        exprs.append(f"TRIM(COALESCE({i_col}, '')) <> ''")
                    if t_col:
                        exprs.append(f"TRIM(COALESCE({t_col}, '')) <> ''")
                    where = (" WHERE " + " OR ".join(exprs)) if exprs else ""
                    try:
                        cur.execute(f"SELECT COUNT(*) FROM '{tbl}'{where}")
                        cnt = int(cur.fetchone()[0] or 0)
                    except Exception:
                        cnt = 0
                    total_cards += cnt
            return int(total_cards)
        except Exception:
            return 0

    def _count_user_correct_cards(u_id: int) -> int:
        try:
            with sqlite3.connect(DB_PATH) as conn:
                row = _safe_fetchone(
                    conn,
                    """
                    SELECT COUNT(DISTINCT COALESCE(TRIM(category),'') || '|' || COALESCE(TRIM(card_key),''))
                    FROM flashcards_practice_log
                    WHERE user_id=? AND is_correct=1
                    """,
                    (u_id,)
                ) or (0,)
                return int(row[0] or 0)
        except Exception:
            return 0

    cards_total = _count_total_cards()
    cards_correct = _count_user_correct_cards(user_id)

    # Устный зачёт: знаменатель — общее число «кусков» (строк) в prepared_lectures,
    # числитель — число УНИКАЛЬНЫХ (topic, chunk_idx) с хотя бы одним верным ответом.
    def _get_prepared_lectures_db() -> str | None:
        try:
            # Попытаемся импортировать путь из govr_bot, если доступен
            import importlib  # type: ignore
            _utils = None
            for name in ("govr_bot.bot.utils", "bot.utils"):
                try:
                    _utils = importlib.import_module(name)
                    break
                except Exception:
                    continue
            db = getattr(_utils, "PREPARED_LECTURES_DB", None) if _utils else None
            if db:
                return str(db)
        except Exception:
            pass
        # Фолбэк на shared/prepared_lectures.db
        repo_root = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
        cand = os.path.join(repo_root, "shared", "prepared_lectures.db")
        return cand if os.path.exists(cand) else None

    def _count_total_chunks() -> int:
        try:
            db = _get_prepared_lectures_db()
            if not db or not os.path.exists(db):
                return 0
            with sqlite3.connect(db) as c2:
                cur2 = c2.cursor()
                cur2.execute("SELECT COUNT(*) FROM prepared_lectures")
                row2 = cur2.fetchone()
                return int(row2[0] or 0)
        except Exception:
            return 0

    def _count_user_correct_chunks(u_id: int) -> int:
        try:
            with sqlite3.connect(DB_PATH) as conn:
                row = _safe_fetchone(
                    conn,
                    """
                    SELECT COUNT(DISTINCT topic || '|' || COALESCE(CAST(chunk_idx AS TEXT),'0'))
                    FROM theory_task_answers
                    WHERE user_id=? AND is_correct=1
                    """,
                    (u_id,)
                ) or (0,)
                return int(row[0] or 0)
        except Exception:
            return 0

    theory_total = _count_total_chunks()
    theory_correct = _count_user_correct_chunks(user_id)

    def _bar(pct: float, size: int = 12) -> str:
        filled = int(round(max(0.0, min(100.0, pct)) / 100 * size))
        return "[" + ("█" * filled) + ("░" * (size - filled)) + "]"

    def _line(title: str, correct: int, total: int) -> str:
        pct = round((correct / total) * 100, 1) if total else 0.0
        return f"{title}: <b>{correct}/{total}</b> ({pct}%) { _bar(pct) }"

    parts = [
        f"<b>Сводка ученика {escape(label)}</b>",
        _line("ЕГЭ тесты", ege_correct, ege_total),
        _line("ОГЭ тесты", oge_correct, oge_total),
        _line("Карточки", cards_correct, cards_total),
        _line("Зачёт по учебнику", theory_correct, theory_total),
    ]

    return "\n".join(parts)

def build_user_progress_text(user_id: int, recent_limit: int = 10) -> str:
    """
    Возвращает HTML-текст со сводной статистикой ученика:
      - общее количество ответов, верных, точность
      - последнее время ответа
      - разрез по типам заданий (test_type)
      - последние ответы (до recent_limit)
    """
    with sqlite3.connect(DB_PATH) as conn:
        # Имя ученика
        full_name, username = get_identity(conn, user_id)
        label = (full_name or username or f"ID {user_id}")

        # Общие итоги
        total_row = _safe_fetchone(
            conn,
            """
            SELECT
              SUM(CASE WHEN TRIM(COALESCE(answered_at, '')) <> '' THEN 1 ELSE 0 END) AS answered,
              SUM(CASE WHEN TRIM(COALESCE(answered_at, '')) <> '' AND CAST(is_correct AS INTEGER)=1 THEN 1 ELSE 0 END) AS correct,
              MAX(CASE WHEN TRIM(COALESCE(answered_at, '')) <> '' THEN answered_at ELSE NULL END) AS last_answer
            FROM test_activity
            WHERE user_id = ?
            """,
            (user_id,)
        ) or (0, 0, None)

        total_answered = int(total_row[0] or 0)
        total_correct = int(total_row[1] or 0)
        last_answer = str(total_row[2] or "—")
        total_incorrect = max(total_answered - total_correct, 0)
        accuracy = round((total_correct / total_answered) * 100, 1) if total_answered else 0.0

        # Разрез по типам заданий
        by_type_rows = _safe_fetchall(
            conn,
            """
            SELECT test_type,
                   SUM(CASE WHEN TRIM(COALESCE(answered_at, '')) <> '' THEN 1 ELSE 0 END) AS answered,
                   SUM(CASE WHEN TRIM(COALESCE(answered_at, '')) <> '' AND CAST(is_correct AS INTEGER)=1 THEN 1 ELSE 0 END) AS correct
            FROM test_activity
            WHERE user_id = ?
            GROUP BY test_type
            ORDER BY test_type
            """,
            (user_id,)
        )

        # Последние ответы
        recent_rows = _safe_fetchall(
            conn,
            """
            SELECT test_type, question_id, answered_at, user_answer,
                   CASE WHEN CAST(is_correct AS INTEGER)=1 THEN 1 ELSE 0 END AS is_correct
            FROM test_activity
            WHERE user_id = ? AND TRIM(COALESCE(answered_at, '')) <> ''
            ORDER BY answered_at DESC
            LIMIT ?
            """,
            (user_id, recent_limit)
        )

    # Формируем HTML
    parts: list[str] = []
    parts.append(f"<b>Успеваемость ученика {escape(label)}</b>")
    def _bar(pct: float, size: int = 12) -> str:
        filled = int(round(max(0.0, min(100.0, pct)) / 100 * size))
        return "[" + ("█" * filled) + ("░" * (size - filled)) + "]"

    parts.append(
        (
            f"Всего ответов: <b>{total_answered}</b>\n"
            f"Верных: <b>{total_correct}</b> | Неверных: <b>{total_incorrect}</b>\n"
            f"Точность: <b>{accuracy}%</b> { _bar(accuracy) }\n"
            f"Последний ответ: {escape(last_answer)}"
        )
    )

    if by_type_rows:
        parts.append("")
        parts.append("<b>По заданиям:</b>")
        for t_type, answered, correct in by_type_rows:
            a = int(answered or 0)
            c = int(correct or 0)
            p = round((c / a) * 100, 1) if a else 0.0
            parts.append(f"№{t_type}: {c}/{a} ({p}%) { _bar(p) }")

    if recent_rows:
        parts.append("")
        parts.append(f"<b>Последние ответы (до {recent_limit}):</b>")
        for t_type, qid, ans_at, user_ans, is_corr in recent_rows:
            status = "✅" if is_corr else "❌"
            safe_ans = escape(user_ans or "—")
            parts.append(
                f"{status} №{t_type}, вопрос ID {qid} — ответ: <b>{safe_ans}</b> ({ans_at})"
            )

    return "\n".join(parts)


def _build_user_progress_text_by_exam(user_id: int, exam: str, recent_limit: int = 10) -> str:
    """
    Версия статистики, отфильтрованная по типу экзамена ("ege" или "oge").

    Логика определения принадлежности вопроса к экзамену:
      - вопрос относится к EGE, если его id найден в БД TESTS_DB_EGE
      - вопрос относится к OGE, если его id найден в БД TESTS_DB_OGE

    Чтобы не перегружать БД, используем кэш `_CACHE_EGE` / `_CACHE_OGE`.
    """
    exam = (exam or "").lower().strip()
    if exam not in {"ege", "oge"}:
        exam = "ege"

    def _get_correct_answer(db_path: str, cache: dict[int, str], question_id: int) -> str | None:
        if question_id in cache:
            return cache[question_id]
        try:
            with sqlite3.connect(db_path) as c:
                cur = c.cursor()
                # Попробуем разные имена колонок
                cur.execute("PRAGMA table_info(tests)")
                cols = {row[1].lower(): row[1] for row in cur.fetchall()}
                corr_col = None
                for cand in ["correct_ans", "correct_answer", "correct", "right_answer", "answer"]:
                    if cand in cols:
                        corr_col = cols[cand]
                        break
                if not corr_col:
                    cache[question_id] = ""
                    return ""
                cur.execute(f"SELECT {corr_col} FROM tests WHERE id=?", (question_id,))
                row = cur.fetchone()
                ans = (row[0] if row else "")
                ans_norm = str(ans).strip().lower()
                cache[question_id] = ans_norm
                return ans_norm
        except Exception:
            cache[question_id] = ""
            return ""

    def _belongs_to_exam(row_test_type: int, _row_qid: int, _row_correct: str) -> bool:
        """
        Принадлежность ответов к экзамену.
        Упрощаем логику: учитываем ВСЕ ответы из test_answers с типом в диапазоне
        экзамена (1..28 для ЕГЭ, 1..19 для ОГЭ), без проверки совпадения эталона.
        Это согласует бота с PDF-отчетом, где берётся сырая статистика по test_answers.
        """
        if row_test_type is None:
            return False
        if exam == "oge":
            return 1 <= int(row_test_type) <= 19
        return 1 <= int(row_test_type) <= 28

    with sqlite3.connect(DB_PATH) as conn:
        # Имя ученика
        full_name, username = get_identity(conn, user_id)
        label = (full_name or username or f"ID {user_id}")

        # Берём из test_answers, чтобы была строка correct_answer для сверки с нужной БД
        rows = _safe_fetchall(
            conn,
            """
            SELECT test_type, question_id, answer_time, user_answer, correct_answer,
                   CASE WHEN CAST(is_correct AS INTEGER)=1 THEN 1 ELSE 0 END AS is_correct
            FROM test_answers
            WHERE user_id = ?
            ORDER BY answer_time DESC, id DESC
            """,
            (user_id,)
        )

    # Подсчёты
    total_answered = 0
    total_correct = 0
    last_answer = None  # строка вида YYYY-MM-DD HH:MM:SS
    by_type: dict[int, tuple[int, int]] = {}  # test_type -> (answered, correct)
    recent_kept: list[tuple[int, int, str, str, int]] = []  # (test_type, qid, answered_at, user_answer, is_corr)

    for t_type, qid, ans_at, user_ans, corr_ans, is_corr in rows:
        # Учитываем только ответы с меткой времени
        if not ans_at or not str(ans_at).strip():
            continue
        try:
            qid_int = int(qid)
        except Exception:
            continue

        # Отбрасываем, если ответ не принадлежит выбранному экзамену
        if not _belongs_to_exam(int(t_type or 0), qid_int, str(corr_ans or "")):
            continue

        total_answered += 1
        total_correct += int(is_corr or 0)
        if not last_answer or str(ans_at) > last_answer:
            last_answer = str(ans_at)

        # by_type
        try:
            key = int(t_type) if t_type is not None else None
        except Exception:
            key = None
        if key is not None:
            a, c = by_type.get(key, (0, 0))
            by_type[key] = (a + 1, c + int(is_corr or 0))

        # для списка последних ответов соберём, потом отсортируем
        recent_kept.append((int(t_type or 0), qid_int, str(ans_at), str(user_ans or "—"), int(is_corr or 0)))

    # Итоговые метрики
    total_incorrect = max(total_answered - total_correct, 0)
    accuracy = round((total_correct / total_answered) * 100, 1) if total_answered else 0.0
    last_answer = last_answer or "—"

    # Формирование текста
    parts: list[str] = []
    parts.append(f"<b>Успеваемость ученика {escape(label)}</b>")

    def _bar(pct: float, size: int = 12) -> str:
        filled = int(round(max(0.0, min(100.0, pct)) / 100 * size))
        return "[" + ("█" * filled) + ("░" * (size - filled)) + "]"

    parts.append(
        (
            f"Всего ответов: <b>{total_answered}</b>\n"
            f"Верных: <b>{total_correct}</b> | Неверных: <b>{total_incorrect}</b>\n"
            f"Точность: <b>{accuracy}%</b> { _bar(accuracy) }\n"
            f"Последний ответ: {escape(last_answer)}"
        )
    )

    # Раздел «по заданиям»: выводим ВСЕ типы текущего экзамена (даже нулевые)
    parts.append("")
    parts.append("<b>По заданиям:</b>")
    max_type = 28 if exam == "ege" else 19
    for t_type in range(1, max_type + 1):
        answered, correct = by_type.get(t_type, (0, 0))
        # Требование: в прогрессе по типам знаменатель всегда 30 (и для ЕГЭ, и для ОГЭ)
        total_per_type = 30
        corr_capped = min(int(correct or 0), total_per_type)
        p = round((corr_capped / total_per_type) * 100, 1) if total_per_type else 0.0
        parts.append(f"№{t_type}: {corr_capped}/{total_per_type} ({p}%) { _bar(p) }")

    if recent_kept:
        parts.append("")
        parts.append(f"<b>Последние ответы (до {recent_limit}):</b>")
        # Сортируем по answered_at DESC и берём первые recent_limit
        recent_kept.sort(key=lambda r: r[2], reverse=True)
        for t_type, qid, ans_at, user_ans, is_corr in recent_kept[:max(0, int(recent_limit))]:
            status = "✅" if is_corr else "❌"
            parts.append(
                f"{status} №{t_type}, вопрос ID {qid} — ответ: <b>{escape(user_ans)}</b> ({ans_at})"
            )

    return "\n".join(parts)


def build_user_progress_text_ege(user_id: int, recent_limit: int = 10) -> str:
    """Обёртка для статистики только по ЕГЭ."""
    return _build_user_progress_text_by_exam(user_id, "ege", recent_limit)


def build_user_progress_text_oge(user_id: int, recent_limit: int = 10) -> str:
    """Обёртка для статистики только по ОГЭ."""
    return _build_user_progress_text_by_exam(user_id, "oge", recent_limit)


# =========================
#   Карточки: сводка с прогресс-барами
# =========================

def build_user_flashcards_text(user_id: int, recent_limit: int = 10) -> str:
    """
    Возвращает HTML-отчёт по карточкам:
      - общий прогресс (correct/total) и бар
      - разрез по категориям (например, inorg/org), по всем встречавшимся и пустые для просмотренных
      - последние попытки
    """
    # Загружаем агрегаты
    with sqlite3.connect(DB_PATH) as conn:
        # Имя ученика
        full_name, username = get_identity(conn, user_id)
        label = (full_name or username or f"ID {user_id}")

        total_row = _safe_fetchone(
            conn,
            """
            SELECT COUNT(*), SUM(CASE WHEN is_correct=1 THEN 1 ELSE 0 END)
            FROM flashcards_practice_log
            WHERE user_id=?
            """,
            (user_id,)
        ) or (0, 0)
        total_attempts = int(total_row[0] or 0)
        total_correct = int(total_row[1] or 0)

        # Разрез по категориям
        by_cat = _safe_fetchall(
            conn,
            """
            SELECT category,
                   COUNT(*) AS total,
                   SUM(CASE WHEN is_correct=1 THEN 1 ELSE 0 END) AS correct
            FROM flashcards_practice_log
            WHERE user_id=?
            GROUP BY category
            ORDER BY category
            """,
            (user_id,)
        )

        # Сколько уникальных карточек увидел по категориям (вдруг по какой-то только просмотры)
        seen_rows = _safe_fetchall(
            conn,
            """
            SELECT category, COUNT(*) AS seen_unique
            FROM flashcards_seen
            WHERE user_id=?
            GROUP BY category
            """,
            (user_id,)
        )
        seen_map = {str(cat or ""): int(cnt or 0) for cat, cnt in seen_rows}

        # Последние ответы
        recent_rows = _safe_fetchall(
            conn,
            """
            SELECT category, card_key, is_correct, created_at
            FROM flashcards_practice_log
            WHERE user_id=?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (user_id, recent_limit)
        )

    def _bar(pct: float, size: int = 12) -> str:
        filled = int(round(max(0.0, min(100.0, pct)) / 100 * size))
        return "[" + ("█" * filled) + ("░" * (size - filled)) + "]"

    parts: list[str] = []
    parts.append(f"<b>Статистика по карточкам</b>\nУченика: {escape(label)}")

    pct_total = round((total_correct / total_attempts) * 100, 1) if total_attempts else 0.0
    parts.append(
        f"Всего попыток: <b>{total_attempts}</b> | Верных: <b>{total_correct}</b>\n"
        f"Точность: <b>{pct_total}%</b> { _bar(pct_total) }"
    )

    # По категориям. Покажем и пустые категории, если они только в seen_map
    parts.append("")
    parts.append("<b>По категориям:</b>")
    cats = sorted({str(c or "") for c, *_ in by_cat} | set(seen_map.keys()))
    for cat in cats:
        # total/correct из практики
        total = 0
        correct = 0
        for c, t, corr in by_cat:
            if str(c or "") == cat:
                total = int(t or 0)
                correct = int(corr or 0)
                break
        pct = round((correct / total) * 100, 1) if total else 0.0
        seen = seen_map.get(cat, 0)
        title = cat if cat else "(без категории)"
        parts.append(f"{escape(title)}: {correct}/{total} ({pct}%) { _bar(pct) }  • видел: {seen}")

    if recent_rows:
        parts.append("")
        parts.append(f"<b>Последние ответы (до {recent_limit}):</b>")
        for cat, key, is_corr, ts in recent_rows:
            status = "✅" if int(is_corr or 0) == 1 else "❌"
            cat_s = escape(cat or "")
            key_s = escape(key or "")
            parts.append(f"{status} {cat_s} • {key_s} — {ts}")

    return "\n".join(parts)


# =========================
#   Устный зачёт (voice по теории): сводка с прогресс-барами
# =========================

def build_user_oral_text(user_id: int, recent_limit: int = 10) -> str:
    """
    Отчёт по устному зачёту: используем таблицу theory_task_answers,
    берём только записи, где answer_type='voice'.

    Показываем:
      - общий прогресс (верных/всего) и бар
      - разрез по темам (topic)
      - последние голосовые ответы
    """
    with sqlite3.connect(DB_PATH) as conn:
        # Имя ученика
        full_name, username = get_identity(conn, user_id)
        label = (full_name or username or f"ID {user_id}")

        total_row = _safe_fetchone(
            conn,
            """
            SELECT COUNT(*), SUM(CASE WHEN is_correct=1 THEN 1 ELSE 0 END)
            FROM theory_task_answers
            WHERE user_id=? AND answer_type='voice'
            """,
            (user_id,)
        ) or (0, 0)
        total_attempts = int(total_row[0] or 0)
        total_correct = int(total_row[1] or 0)

        by_topic = _safe_fetchall(
            conn,
            """
            SELECT topic,
                   COUNT(*) AS total,
                   SUM(CASE WHEN is_correct=1 THEN 1 ELSE 0 END) AS correct
            FROM theory_task_answers
            WHERE user_id=? AND answer_type='voice'
            GROUP BY topic
            ORDER BY topic
            """,
            (user_id,)
        )

        recent_rows = _safe_fetchall(
            conn,
            """
            SELECT topic, question_text, is_correct, created_at
            FROM theory_task_answers
            WHERE user_id=? AND answer_type='voice'
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (user_id, recent_limit)
        )

    def _bar(pct: float, size: int = 12) -> str:
        filled = int(round(max(0.0, min(100.0, pct)) / 100 * size))
        return "[" + ("█" * filled) + ("░" * (size - filled)) + "]"

    parts: list[str] = []
    parts.append(f"<b>Устный зачёт</b>\nУченика: {escape(label)}")

    pct_total = round((total_correct / total_attempts) * 100, 1) if total_attempts else 0.0
    parts.append(
        f"Всего ответов: <b>{total_attempts}</b> | Верных: <b>{total_correct}</b>\n"
        f"Точность: <b>{pct_total}%</b> { _bar(pct_total) }"
    )

    # Соберём полный список тем из prepared_lectures, чтобы показать и нулевые
    prepared_topics: set[str] = set()
    try:
        # Попытка 1: импорт из govr_bot
        import importlib
        _utils = None
        for name in ("govr_bot.bot.utils", "bot.utils"):
            try:
                _utils = importlib.import_module(name)
                break
            except Exception:
                continue
        _pl_db = getattr(_utils, "PREPARED_LECTURES_DB", None) if _utils else None
        if not _pl_db:
            # Фолбэк по путям репозитория
            repo_root = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
            cand1 = os.path.join(repo_root, "shared", "prepared_lectures.db")
            cand2 = os.path.join(repo_root, "govr_bot", "bot", "prepared_lectures.db")
            _pl_db = cand1 if os.path.exists(cand1) else cand2
        with sqlite3.connect(str(_pl_db)) as _conn2:
            _cur2 = _conn2.cursor()
            try:
                _cur2.execute("SELECT DISTINCT topic FROM prepared_lectures")
                prepared_topics = {str(r[0]) for r in _cur2.fetchall() if r and r[0]}
            except sqlite3.Error:
                prepared_topics = set()
    except Exception:
        prepared_topics = set()

    # Карту результатов по темам + добавим нули для отсутствующих
    by_topic_map: dict[str, tuple[int, int]] = {}
    for topic, total, correct in by_topic:
        by_topic_map[str(topic or "")] = (int(total or 0), int(correct or 0))
    for t in prepared_topics:
        if t not in by_topic_map:
            by_topic_map[t] = (0, 0)

    if by_topic_map:
        parts.append("")
        parts.append("<b>По темам:</b>")

        # Желаемый порядок и группировка разделов
        ordered_sections: list[tuple[str, list[str]]] = [
            (
                "Начала химии",
                [
                    "Строение атома",
                    "Периодический закон",
                    "Химическая связь",
                    "Формула вещества",
                    "Оксиды",
                    "Основания и амфотерные гидроксиды",
                    "Кислоты",
                    "Соли",
                ],
            ),
            (
                "Химия элементов",
                [
                    "ОВР",
                    "Водород",
                    "Галогены",
                    "Кислород",
                    "Сера",
                    "Азот и фосфор",
                    "Углерод и кремний",
                    "Хром, марганец и алюминий",
                    "Железо, медь, серебро, цинк",
                ],
            ),
            (
                "Органическая химия",
                [
                    "Алканы",
                    "Алкены",
                    "Алкины",
                    "Альдегиды и кетоны",
                    "Аминокислоты и белки",
                    "Амины",
                    "Арены",
                    "Именные реакции",
                    "Карбоновые кислоты и эфиры",
                    "Применение орг веществ",
                    "Спирты",
                    "Углеводы",
                    "Фенол",
                    "Циклоалканы и диены",
                ],
            ),
        ]

        # Отрисовываем по разделам в заданном порядке
        used_topics: set[str] = set()
        for section_title, topics in ordered_sections:
            parts.append("")
            parts.append(f"<u><b>{escape(section_title)}</b></u>")
            for topic in topics:
                used_topics.add(topic)
                t, c = by_topic_map.get(topic, (0, 0))
                pct = round((c / t) * 100, 1) if t else 0.0
                title = escape(topic)
                parts.append(f"{title}: {c}/{t} ({pct}%) { _bar(pct) }")

        # Выведем оставшиеся темы (если есть) в конце, чтобы ничего не потерять
        remaining = [t for t in sorted(by_topic_map.keys()) if t and t not in used_topics]
        if remaining:
            parts.append("")
            parts.append("<u><b>Прочее</b></u>")
            for topic in remaining:
                t, c = by_topic_map.get(topic, (0, 0))
                pct = round((c / t) * 100, 1) if t else 0.0
                title = escape(topic)
                parts.append(f"{title}: {c}/{t} ({pct}%) { _bar(pct) }")

    if recent_rows:
        parts.append("")
        parts.append(f"<b>Последние ответы (до {recent_limit}):</b>")
        for topic, qtext, is_corr, ts in recent_rows:
            status = "✅" if int(is_corr or 0) == 1 else "❌"
            t = escape(topic or "")
            q = escape((qtext or "").strip()[:60])
            parts.append(f"{status} {t} — {q} ({ts})")

    return "\n".join(parts)