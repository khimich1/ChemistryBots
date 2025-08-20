import os
import sqlite3
from dotenv import load_dotenv

# Загружаем .env и корректно определяем путь к базе с тестами
load_dotenv()

# База с вопросами тестов (таблица `tests`).
# 1) Если задано в .env (TESTS_DB_PATH) — используем его
# 2) Иначе берём дефолт: ChemistryBots/shared/tests1.db
_THIS_DIR = os.path.dirname(__file__)                             # govr_bot/bot/services
_PROJECT_ROOT = os.path.normpath(os.path.join(_THIS_DIR, "..", "..", ".."))
DB_FILE = os.getenv("TESTS_DB_PATH") or os.path.join(_PROJECT_ROOT, "shared", "tests1.db")


def _ensure_issue_columns():
    """
    Гарантирует наличие столбцов для жалоб в таблице tests:
      - has_issue INTEGER DEFAULT 0         (флаг скрытия вопроса до исправления)
      - issue_reason TEXT DEFAULT ''        (последняя причина)
      - issue_reported_at TEXT DEFAULT ''   (когда пожаловались)
    Функция безопасна при многократном вызове.
    """
    try:
        with sqlite3.connect(DB_FILE) as conn:
            c = conn.cursor()
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS tests (
                    id INTEGER PRIMARY KEY,
                    type INTEGER,
                    question TEXT,
                    options TEXT,
                    correct_answer TEXT,
                    explanation TEXT,
                    hint TEXT,
                    detailed_explanation TEXT
                )
                """
            )
            cols = {row[1] for row in c.execute("PRAGMA table_info(tests)")}
            if "has_issue" not in cols:
                c.execute("ALTER TABLE tests ADD COLUMN has_issue INTEGER DEFAULT 0")
            if "issue_reason" not in cols:
                c.execute("ALTER TABLE tests ADD COLUMN issue_reason TEXT DEFAULT ''")
            if "issue_reported_at" not in cols:
                c.execute("ALTER TABLE tests ADD COLUMN issue_reported_at TEXT DEFAULT ''")
            conn.commit()
    except Exception:
        # Не падаем, если БД только для чтения/без таблицы tests – просто пропускаем.
        pass


_ensure_issue_columns()


def _detect_answer_column(conn: sqlite3.Connection) -> str:
    """
    Возвращает корректное имя колонки с правильным ответом в таблице `tests`.
    Поддерживает оба варианта: `correct_answer` (старое имя) и `correct_ans` (новое имя).
    """
    c = conn.cursor()
    c.execute("PRAGMA table_info(tests)")
    cols = {row[1] for row in c.fetchall()}  # row[1] = name
    if "correct_answer" in cols:
        return "correct_answer"
    if "correct_ans" in cols:
        return "correct_ans"
    # Если ни одной знакомой колонки нет — бросаем понятную ошибку
    raise sqlite3.OperationalError(
        "В таблице tests нет колонки с правильным ответом (correct_answer/correct_ans)."
    )


def get_all_tests_types():
    """
    Получает список уникальных типов тестов (например, 1...28)
    """
    _ensure_issue_columns()
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute("SELECT DISTINCT type FROM tests ORDER BY type")
        # Оставляем только значения, которые не None и не пустые строки
        return [row[0] for row in c.fetchall() if row[0] not in (None, '')]


def get_questions_by_type(test_type, limit: int = 30):
    """
    Получает все вопросы для заданного типа теста (по порядку id)
    Возвращает список dict-ов: id, question, options, correct_answer, explanation, hint, detailed_explanation
    Не более `limit` (по умолчанию 30) вопросов.
    """
    _ensure_issue_columns()
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        ans_col = _detect_answer_column(conn)
        safe_limit = int(limit) if isinstance(limit, int) and limit > 0 else 30
        sql = (
            f"""
            SELECT id, question, options, {ans_col} AS correct_answer, explanation, hint, detailed_explanation
            FROM tests
            WHERE type=? AND COALESCE(has_issue, 0)=0
            ORDER BY id
            LIMIT {safe_limit}
            """
        )
        c.execute(sql, (test_type,))
        return [
            dict(
                id=row[0],
                question=row[1],
                options=row[2] or "",
                correct_answer=row[3] or "",
                explanation=row[4] or "",
                hint=row[5] or "",
                detailed_explanation=row[6] or ""
            )
            for row in c.fetchall()
        ]


def get_question_by_id(q_id):
    """
    Получает один вопрос по его id, с detailed_explanation
    """
    _ensure_issue_columns()
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        ans_col = _detect_answer_column(conn)
        sql = (
            f"SELECT id, type, question, options, {ans_col} AS correct_answer, "
            f"explanation, hint, detailed_explanation, COALESCE(has_issue,0), COALESCE(issue_reason,'') "
            f"FROM tests WHERE id=?"
        )
        c.execute(sql, (q_id,))
        row = c.fetchone()
        if row:
            return dict(
                id=row[0],
                type=row[1],
                question=row[2],
                options=row[3] or "",
                correct_answer=row[4] or "",
                explanation=row[5] or "",
                hint=row[6] or "",
                detailed_explanation=row[7] or "",
                has_issue=bool(row[8] or 0),
                issue_reason=row[9] or ""
            )
        else:
            return None


def mark_question_issue(q_id: int, reason: str | None = None) -> None:
    """Помечает вопрос как проблемный (глобально скрываем) с опциональной причиной."""
    _ensure_issue_columns()
    try:
        with sqlite3.connect(DB_FILE) as conn:
            c = conn.cursor()
            c.execute(
                """
                UPDATE tests
                SET has_issue=1,
                    issue_reason=COALESCE(?, issue_reason),
                    issue_reported_at=strftime('%Y-%m-%d %H:%M:%S','now')
                WHERE id=?
                """,
                (reason or None, q_id),
            )
            conn.commit()
    except Exception:
        # Безопасно игнорируем, чтобы не ломать тестирование, даже если нет прав на запись
        pass

