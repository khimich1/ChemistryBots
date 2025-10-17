import os
import sqlite3
import asyncio
from datetime import datetime
from typing import Optional

from config import TESTS_DB_TEACHER


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """Создаёт недостающие таблицы по образцу баз ЕГЭ/ОГЭ.

    Таблица tests — совместимая по именам колонок:
      id, type, question, options, correct_ans|correct_answer, explanation, hint, detailed_explanation
    Мы используем колонку correct_ans (как просили), но также создаём alias correct_answer
    для совместимости с клиентским кодом (если колонка отсутствует — добавляем).

    Таблица images — хранит бинарные данные изображений.
    """
    c = conn.cursor()
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS tests (
            id INTEGER PRIMARY KEY,
            filename TEXT,
            type INTEGER,
            question TEXT,
            options TEXT,
            correct_ans TEXT,
            explanation TEXT,
            hint TEXT,
            detailed_explanation TEXT
        )
        """
    )

    # Если нет колонки correct_answer — создадим для совместимости
    c.execute("PRAGMA table_info(tests)")
    cols = {row[1] for row in c.fetchall()}
    if "correct_answer" not in cols:
        try:
            c.execute("ALTER TABLE tests ADD COLUMN correct_answer TEXT")
        except Exception:
            pass

    # Таблица изображений
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT,
            mime_type TEXT,
            size_bytes INTEGER,
            data BLOB,
            created_at TEXT
        )
        """
    )

    # Таблица наборов заданий преподавателя (тестов): заголовок + дата создания
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS teacher_task_sets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            created_at TEXT,
            teacher_id INTEGER
        )
        """
    )

    # Добавим teacher_id в teacher_task_sets, если его нет (миграция старой БД)
    try:
        c.execute("PRAGMA table_info(teacher_task_sets)")
        cols = {row[1] for row in c.fetchall()}
        if "teacher_id" not in cols:
            try:
                c.execute("ALTER TABLE teacher_task_sets ADD COLUMN teacher_id INTEGER")
            except Exception:
                pass
    except Exception:
        pass

    # Добавим колонку set_id в tests при необходимости (связь вопроса с набором)
    try:
        c.execute("PRAGMA table_info(tests)")
        cols = {row[1] for row in c.fetchall()}
        if "set_id" not in cols:
            try:
                c.execute("ALTER TABLE tests ADD COLUMN set_id INTEGER")
            except Exception:
                pass
        if "teacher_id" not in cols:
            try:
                c.execute("ALTER TABLE tests ADD COLUMN teacher_id INTEGER")
            except Exception:
                pass
    except Exception:
        pass
    conn.commit()


def _backfill_sets_teacher(conn: sqlite3.Connection, teacher_id: int) -> None:
    """Для старых наборов без teacher_id проставляет владельца по авторам заданий внутри набора."""
    try:
        c = conn.cursor()
        # Если в tests нет teacher_id — добавим
        try:
            c.execute("PRAGMA table_info(tests)")
            cols = {row[1] for row in c.fetchall()}
            if "teacher_id" not in cols:
                try:
                    c.execute("ALTER TABLE tests ADD COLUMN teacher_id INTEGER")
                except Exception:
                    pass
        except Exception:
            pass
        # Проставим teacher_id у наборов, если внутри есть задания автора
        try:
            c.execute(
                """
                UPDATE teacher_task_sets
                SET teacher_id = ?
                WHERE teacher_id IS NULL AND id IN (
                  SELECT DISTINCT set_id FROM tests WHERE teacher_id = ? OR filename = ?
                )
                """,
                (int(teacher_id), int(teacher_id), str(teacher_id)),
            )
            conn.commit()
        except Exception:
            pass
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass


def _connect() -> sqlite3.Connection:
    path = TESTS_DB_TEACHER
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
    # Укрепляем соединение для снижения конфликтов блокировок
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA busy_timeout=30000;")
    except Exception:
        # Не валим выполнение, если PRAGMA недоступны
        pass
    _ensure_schema(conn)
    return conn


def save_image(filename: str, mime_type: str, data: bytes) -> int:
    """Сохраняет изображение в images и возвращает id."""
    with _connect() as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO images (filename, mime_type, size_bytes, data, created_at) VALUES (?, ?, ?, ?, ?)",
            (filename, mime_type, len(data or b""), data, datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")),
        )
        conn.commit()
        return int(c.lastrowid)


def add_teacher_task(*, teacher_tg_id: int, question_text: str, image_id: Optional[int], correct_answer: str, set_id: Optional[int] = None) -> int:
    """Добавляет задание в tests. Поля:
    - filename: Telegram ID преподавателя (как строка)
    - question: текст задания
    - options: ID изображения (или список ID через запятую), если есть; иначе пусто
    - correct_ans: верный ответ (строкой)
    Возвращает id созданной записи.
    """
    options_value = str(image_id) if image_id is not None else ""
    with _connect() as conn:
        c = conn.cursor()
        # Привяжем вопрос к автору (teacher_id)
        try:
            c.execute(
                "INSERT INTO tests (filename, type, question, options, correct_ans, correct_answer, set_id, teacher_id) VALUES (?, NULL, ?, ?, ?, ?, ?, ?)",
                (str(teacher_tg_id), question_text, options_value, str(correct_answer), str(correct_answer), int(set_id) if set_id is not None else None, int(teacher_tg_id)),
            )
        except sqlite3.OperationalError:
            # Если нет колонки teacher_id — добавим и повторим
            try:
                c.execute("ALTER TABLE tests ADD COLUMN teacher_id INTEGER")
            except Exception:
                pass
            c.execute(
                "INSERT INTO tests (filename, type, question, options, correct_ans, correct_answer, set_id, teacher_id) VALUES (?, NULL, ?, ?, ?, ?, ?, ?)",
                (str(teacher_tg_id), question_text, options_value, str(correct_answer), str(correct_answer), int(set_id) if set_id is not None else None, int(teacher_tg_id)),
            )
        conn.commit()
        return int(c.lastrowid)


# ── Работа с наборами заданий преподавателя ─────────────────────────────────────────
def list_task_sets(*, teacher_id: int | None = None) -> list[dict]:
    with _connect() as conn:
        c = conn.cursor()
        if teacher_id is not None:
            tid = int(teacher_id)
            _backfill_sets_teacher(conn, tid)
            # Пытаемся выбрать по teacher_id, а для старых наборов (без teacher_id)
            # берём те, где есть хотя бы одно задание автора (по tests.teacher_id или filename = tg_id)
            try:
                c.execute(
                    """
                    SELECT s.id, s.title, s.created_at
                    FROM teacher_task_sets s
                    LEFT JOIN tests t ON t.set_id = s.id
                    WHERE (s.teacher_id = ?)
                       OR (s.teacher_id IS NULL AND (t.teacher_id = ? OR t.filename = ?))
                    GROUP BY s.id
                    ORDER BY s.id DESC
                    """,
                    (tid, tid, str(tid)),
                )
            except sqlite3.OperationalError as e:
                # Миграции на лету
                msg = str(e).lower()
                if "teacher_task_sets" in msg and "no such column" in msg:
                    try:
                        c.execute("ALTER TABLE teacher_task_sets ADD COLUMN teacher_id INTEGER")
                    except Exception:
                        pass
                if "tests" in msg and "no such column" in msg:
                    try:
                        c.execute("ALTER TABLE tests ADD COLUMN teacher_id INTEGER")
                    except Exception:
                        pass
                # Повторим запрос
                c.execute(
                    """
                    SELECT s.id, s.title, s.created_at
                    FROM teacher_task_sets s
                    LEFT JOIN tests t ON t.set_id = s.id
                    WHERE (s.teacher_id = ?)
                       OR (s.teacher_id IS NULL AND (t.teacher_id = ? OR t.filename = ?))
                    GROUP BY s.id
                    ORDER BY s.id DESC
                    """,
                    (tid, tid, str(tid)),
                )
        else:
            c.execute("SELECT id, title, created_at FROM teacher_task_sets ORDER BY id DESC")
        rows = c.fetchall()
    return [{"id": int(r[0]), "title": r[1] or "", "created_at": r[2]} for r in rows]


async def list_task_sets_async(*, teacher_id: int | None = None) -> list[dict]:
    """Асинхронная обёртка над list_task_sets: выполняет работу в пуле потоков,
    чтобы не блокировать event loop aiogram."""
    return await asyncio.to_thread(list_task_sets, teacher_id=teacher_id)


def create_task_set(title: str, *, teacher_id: int | None = None) -> int:
    with _connect() as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO teacher_task_sets (title, created_at, teacher_id) VALUES (?, ?, ?)",
            (title.strip(), datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), int(teacher_id) if teacher_id else None),
        )
        conn.commit()
        return int(c.lastrowid)


def get_task_set_by_id(set_id: int) -> dict | None:
    with _connect() as conn:
        c = conn.cursor()
        c.execute("SELECT id, title, created_at FROM teacher_task_sets WHERE id=?", (int(set_id),))
        row = c.fetchone()
        if not row:
            return None
        return {"id": int(row[0]), "title": row[1] or "", "created_at": row[2]}


def list_tasks_in_set(set_id: int) -> list[dict]:
    with _connect() as conn:
        c = conn.cursor()
        # Вытаскиваем id, question и image options
        c.execute(
            "SELECT id, question, options, correct_ans FROM tests WHERE set_id=? ORDER BY id",
            (int(set_id),),
        )
        rows = c.fetchall()
    return [
        {"id": int(r[0]), "question": r[1] or "", "options": r[2] or "", "correct_answer": r[3] or ""}
        for r in rows
    ]


def count_tasks_in_set(set_id: int) -> int:
    with _connect() as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(1) FROM tests WHERE set_id=?", (int(set_id),))
        row = c.fetchone()
        return int(row[0]) if row and row[0] is not None else 0


def delete_task_set(set_id: int) -> bool:
    """Удаляет набор и все вопросы, привязанные к нему."""
    with _connect() as conn:
        c = conn.cursor()
        try:
            c.execute("DELETE FROM tests WHERE set_id=?", (int(set_id),))
            c.execute("DELETE FROM teacher_task_sets WHERE id=?", (int(set_id),))
            conn.commit()
            return True
        except Exception:
            return False


def compute_teacher_set_results(set_id: int) -> dict:
    """Возвращает итоги по набору преподавателя по последним ответам каждого ученика.

    Формат:
    {
      'title': str,
      'qids': [int, ...],
      'results': [ { 'user_id': int, 'label': str, 'correct': int, 'total': int, 'pct': float }, ... ]
    }
    """
    # 1) Получим заголовок и список вопросов набора
    info = get_task_set_by_id(int(set_id))
    title = (info or {}).get("title") or f"Набор {set_id}"
    tasks = list_tasks_in_set(int(set_id))
    qids = [int(t.get("id")) for t in tasks]
    if not qids:
        return {"title": title, "qids": [], "results": []}

    # 2) Ищем ответы по этим id вопросов в общей базе ответов
    from config import DB_PATH
    import sqlite3
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            placeholders = ",".join(["?"] * len(qids))
            # Берём последние по каждому вопросу ответы каждого пользователя
            # Сначала всех пользователей, у кого есть ответы на эти id
            cur.execute(
                f"SELECT DISTINCT user_id FROM test_answers WHERE question_id IN ({placeholders})",
                [int(q) for q in qids],
            )
            user_ids = [int(r[0]) for r in cur.fetchall()]

            results: list[dict] = []
            if not user_ids:
                return {"title": title, "qids": qids, "results": []}

            # Для подписи попробуем взять имя/username из prepod_bot базы
            def _get_identity(cn: sqlite3.Connection, uid: int) -> tuple[str | None, str | None]:
                try:
                    c2 = cn.cursor()
                    c2.execute(
                        "SELECT NULLIF(TRIM(full_name), ''), NULLIF(TRIM(username), '') FROM user_profiles WHERE user_id=?",
                        (int(uid),),
                    )
                    row = c2.fetchone()
                    if row and (row[0] or row[1]):
                        return row[0], row[1]
                    c2.execute(
                        "SELECT NULLIF(TRIM(full_name), ''), NULLIF(TRIM(username), '') FROM test_answers WHERE user_id=? ORDER BY answer_time DESC LIMIT 1",
                        (int(uid),),
                    )
                    row = c2.fetchone()
                    if row:
                        return row[0], row[1]
                except Exception:
                    pass
                return None, None

            for uid in user_ids:
                last: dict[int, int | None] = {int(q): None for q in qids}
                try:
                    cur.execute(
                        f"SELECT question_id, is_correct, id FROM test_answers WHERE user_id=? AND question_id IN ({placeholders}) ORDER BY id",
                        [int(uid), *[int(q) for q in qids]],
                    )
                    for qid, is_corr, _rid in cur.fetchall():
                        if int(qid) in last:
                            last[int(qid)] = None if is_corr is None else int(is_corr)
                except sqlite3.OperationalError:
                    pass
                correct = sum(1 for v in last.values() if v == 1)
                total = len(qids)
                pct = round((correct / total) * 100.0, 1) if total else 0.0
                full_name, username = _get_identity(conn, int(uid))
                label = full_name or username or f"ID {uid}"
                results.append({"user_id": int(uid), "label": label, "correct": correct, "total": total, "pct": pct})

            results.sort(key=lambda r: (-r['correct'], str(r['label']).lower()))
            return {"title": title, "qids": qids, "results": results}
    except Exception:
        return {"title": title, "qids": qids, "results": []}


