import os
import re
import sqlite3
from typing import List, Dict, Optional
from dotenv import load_dotenv

# Загружаем переменные окружения (.env)
load_dotenv()

_THIS_DIR = os.path.dirname(__file__)                             # govr_bot/bot/services
_PROJECT_ROOT = os.path.normpath(os.path.join(_THIS_DIR, "..", "..", ".."))

# Путь к БД с заданиями преподавателей
DB_FILE = os.getenv("TESTS_DB_TEACHER") or os.path.join(_PROJECT_ROOT, "shared", "test_teacher.db")

# Путь к общей БД ответов, где есть таблица teacher с именами преподавателей
ANSWERS_DB = os.getenv("DB_ANSWERS") or os.path.join(_PROJECT_ROOT, "shared", "test_answers.db")


def _detect_answer_column(conn: sqlite3.Connection) -> str:
    """Определяем имя колонки с правильным ответом: correct_answer или correct_ans"""
    c = conn.cursor()
    c.execute("PRAGMA table_info(tests)")
    cols = {row[1] for row in c.fetchall()}
    if "correct_answer" in cols:
        return "correct_answer"
    if "correct_ans" in cols:
        return "correct_ans"
    # по умолчанию
    return "correct_answer"


def _extract_teacher_id_from_filename(filename: str) -> Optional[int]:
    """Ищем первое целое число в имени файла как id преподавателя."""
    if not filename:
        return None
    m = re.search(r"(\d+)", str(filename))
    try:
        return int(m.group(1)) if m else None
    except Exception:
        return None


def _get_teacher_name(teacher_id: Optional[int]) -> str:
    """Возвращает имя преподавателя из таблицы teacher в ANSWERS_DB.

    Поддерживаем возможные схемы:
    - teacher(id INTEGER PRIMARY KEY, name TEXT)
    - teacher(teacher_id INTEGER PRIMARY KEY, name TEXT)
    - teacher(id INTEGER, surname TEXT, name TEXT)
    Если ничего не нашли — возвращаем 'Преподаватель {id}' либо 'Неизвестный'.
    """
    if teacher_id is None:
        return "Неизвестный"
    try:
        with sqlite3.connect(ANSWERS_DB) as conn:
            c = conn.cursor()
            # Определяем столбцы
            c.execute("PRAGMA table_info(teacher)")
            cols = {row[1] for row in c.fetchall()}
            if not cols:
                return f"Преподаватель {teacher_id}"
            # Вариант: tg_id + name (как в вашей БД)
            if {"tg_id", "name"}.issubset(cols):
                c.execute("SELECT name FROM teacher WHERE tg_id=?", (teacher_id,))
                row = c.fetchone()
                if row and row[0]:
                    return str(row[0])
            # Вариант: id + name
            if {"id", "name"}.issubset(cols):
                c.execute("SELECT name FROM teacher WHERE id=?", (teacher_id,))
                row = c.fetchone()
                if row and row[0]:
                    return str(row[0])
            # Вариант: teacher_id + name
            if {"teacher_id", "name"}.issubset(cols):
                c.execute("SELECT name FROM teacher WHERE teacher_id=?", (teacher_id,))
                row = c.fetchone()
                if row and row[0]:
                    return str(row[0])
            # Вариант: id + surname + name
            if {"id", "surname", "name"}.issubset(cols):
                c.execute("SELECT surname, name FROM teacher WHERE id=?", (teacher_id,))
                row = c.fetchone()
                if row and (row[0] or row[1]):
                    return (str(row[0] or "").strip() + " " + str(row[1] or "").strip()).strip()
    except Exception:
        pass
    return f"Преподаватель {teacher_id}"


def list_test_groups() -> List[Dict]:
    """Возвращает список групп тестов по filename.

    Каждый элемент: { 'key': int, 'filename': str, 'teacher_id': int|None, 'teacher_name': str }
    Ключ 'key' — стабильный индекс по отсортированному списку имён.
    """
    try:
        with sqlite3.connect(DB_FILE) as conn:
            c = conn.cursor()
            c.execute("SELECT DISTINCT filename FROM tests WHERE TRIM(COALESCE(filename,''))<>'' ORDER BY filename")
            filenames = [row[0] for row in c.fetchall() if row and row[0]]
    except Exception:
        filenames = []
    groups: List[Dict] = []
    for idx, fn in enumerate(filenames):
        t_id = _extract_teacher_id_from_filename(fn)
        t_name = _get_teacher_name(t_id)
        groups.append({
            "key": idx,
            "filename": fn,
            "teacher_id": t_id,
            "teacher_name": t_name,
        })
    return groups


def _filename_by_key(key: int) -> Optional[str]:
    groups = list_test_groups()
    for g in groups:
        if int(g["key"]) == int(key):
            return str(g["filename"])
    return None


def teacher_test_type(filename: str) -> int:
    """Стабильное целое для test_type (для журналирования/прогресса)."""
    # Смещаем диапазон, чтобы не пересекалось с ЕГЭ/ОГЭ
    base = 20000
    try:
        h = abs(hash(str(filename))) % 10000
        return base + int(h)
    except Exception:
        return base + 9999


def get_questions_by_filename(filename: str, limit: int = 30) -> List[Dict]:
    """Возвращает до 30 вопросов из таблицы tests для указанного filename."""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            c = conn.cursor()
            ans_col = _detect_answer_column(conn)
            safe_limit = int(limit) if isinstance(limit, int) and limit > 0 else 30
            sql = (
                f"""
                SELECT id, question, options, {ans_col} AS correct_answer, explanation, hint, detailed_explanation
                FROM tests
                WHERE filename=?
                ORDER BY id
                LIMIT {safe_limit}
                """
            )
            c.execute(sql, (filename,))
            return [
                dict(
                    id=row[0],
                    question=row[1],
                    options=row[2] or "",
                    correct_answer=row[3] or "",
                    explanation=row[4] or "",
                    hint=row[5] or "",
                    detailed_explanation=row[6] or "",
                )
                for row in c.fetchall()
            ]
    except Exception:
        return []


def get_question_by_id(q_id: int) -> Optional[Dict]:
    try:
        with sqlite3.connect(DB_FILE) as conn:
            c = conn.cursor()
            ans_col = _detect_answer_column(conn)
            c.execute(
                f"SELECT id, question, options, {ans_col} AS correct_answer, explanation, hint, detailed_explanation FROM tests WHERE id=?",
                (int(q_id),),
            )
            row = c.fetchone()
            if row:
                return dict(
                    id=row[0],
                    question=row[1],
                    options=row[2] or "",
                    correct_answer=row[3] or "",
                    explanation=row[4] or "",
                    hint=row[5] or "",
                    detailed_explanation=row[6] or "",
                )
    except Exception:
        pass
    return None


# ===== КАРТИНКИ И ВОПРОСЫ С КАРТИНКАМИ =====

def get_image_by_id(image_id: int) -> Optional[Dict]:
    """Читает изображение из таблицы images по id (BLOB в поле data)."""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            c = conn.cursor()
            c.execute(
                "SELECT id, filename, mime_type, size_bytes, data, created_at FROM images WHERE id=?",
                (int(image_id),),
            )
            row = c.fetchone()
            if row:
                return {
                    "id": row[0],
                    "filename": row[1],
                    "mime_type": row[2],
                    "size_bytes": row[3],
                    "data": row[4],
                    "created_at": row[5],
                }
    except Exception:
        pass
    return None


def get_question_with_image(q_id: int) -> Optional[Dict]:
    """Возвращает вопрос и подтягивает изображения по ID из options (если там числа)."""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            c = conn.cursor()
            ans_col = _detect_answer_column(conn)
            c.execute(
                f"SELECT id, question, options, {ans_col} AS correct_answer, explanation, hint, detailed_explanation FROM tests WHERE id=?",
                (int(q_id),),
            )
            row = c.fetchone()
            if not row:
                return None
            q = {
                "id": row[0],
                "question": row[1],
                "options": row[2] or "",
                "correct_answer": row[3] or "",
                "explanation": row[4] or "",
                "hint": row[5] or "",
                "detailed_explanation": row[6] or "",
            }
            opt = (q.get("options") or "").replace(" ", "")
            # Если options это одно число или список чисел — трактуем как id(ы) изображений
            if opt and all(ch.isdigit() or ch == "," for ch in opt):
                ids = [int(x) for x in opt.split(",") if x.strip().isdigit()]
                images = []
                for img_id in ids:
                    img = get_image_by_id(img_id)
                    if img:
                        images.append(img)
                if images:
                    if len(images) == 1:
                        q["image"] = images[0]
                    else:
                        q["images"] = images
                    q["options"] = ""  # не показываем числовые id как текст
            return q
    except Exception:
        return None


