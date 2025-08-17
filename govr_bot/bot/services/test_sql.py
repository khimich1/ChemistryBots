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

def get_all_tests_types():
    """
    Получает список уникальных типов тестов (например, 1...28)
    """
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute("SELECT DISTINCT type FROM tests ORDER BY type")
        # Оставляем только значения, которые не None и не пустые строки
        return [row[0] for row in c.fetchall() if row[0] not in (None, '')]

def get_questions_by_type(test_type):
    """
    Получает все вопросы для заданного типа теста (по порядку id)
    Возвращает список dict-ов: id, question, options, correct_answer, explanation, hint, detailed_explanation
    """
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute(
            "SELECT id, question, options, correct_answer, explanation, hint, detailed_explanation "
            "FROM tests WHERE type=? ORDER BY id",
            (test_type,)
        )
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
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute(
            "SELECT id, type, question, options, correct_answer, explanation, hint, detailed_explanation "
            "FROM tests WHERE id=?",
            (q_id,)
        )
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
                detailed_explanation=row[7] or ""
            )
        else:
            return None


