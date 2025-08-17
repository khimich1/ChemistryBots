import os
import sqlite3
from datetime import datetime

# Единая БД ответов в корне проекта: ChemistryBots/shared/test_answers.db
_THIS_DIR = os.path.dirname(__file__)  # govr_bot/bot/services
_PROJECT_ROOT = os.path.normpath(os.path.join(_THIS_DIR, "..", "..", ".."))
DB_FILE = os.getenv("DB_ANSWERS") or os.path.join(_PROJECT_ROOT, "shared", "test_answers.db")
  # Имя файла с базой данных

# 1. Создаём таблицу ответов (вызывается один раз при запуске)
def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS test_answers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT,
                answer_time TEXT,
                test_type INTEGER,
                question_id INTEGER,
                question_text TEXT,
                user_answer TEXT,
                correct_answer TEXT,
                is_correct INTEGER
            )
        ''')
        conn.commit()
        # --- Таблица ответов на задания из теории ---
        c.execute('''
            CREATE TABLE IF NOT EXISTS theory_task_answers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT,
                topic TEXT,
                chunk_idx INTEGER,
                question_index INTEGER,
                question_text TEXT,
                answer_text TEXT,
                answer_type TEXT,
                voice_file_id TEXT,
                is_correct INTEGER,
                feedback TEXT,
                created_at TEXT
            )
        ''')
        conn.commit()
        # Гарантируем наличие новых столбцов при обновлении
        cols = {row[1] for row in c.execute("PRAGMA table_info(theory_task_answers)")}
        if "is_correct" not in cols:
            c.execute("ALTER TABLE theory_task_answers ADD COLUMN is_correct INTEGER")
        if "feedback" not in cols:
            c.execute("ALTER TABLE theory_task_answers ADD COLUMN feedback TEXT")
        conn.commit()
    # --- Инициализация таблицы активности вопросов ---
    init_activity_table()

# 2. Запись одного ответа в таблицу test_answers
def save_test_answer(user_id, username, test_type, question_id, question_text, user_answer, correct_answer, is_correct):
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute('''
            INSERT INTO test_answers
            (user_id, username, answer_time, test_type, question_id, question_text, user_answer, correct_answer, is_correct)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            user_id,
            username,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            test_type,
            question_id,
            question_text,
            user_answer,
            correct_answer,
            int(is_correct)
        ))
        conn.commit()

# 3. Сохраняем прогресс теста (таблица test_progress)
def save_test_progress(user_id, test_type, idx, q_ids):
    """
    Сохраняет прогресс теста: пользователя, номер теста, текущий вопрос и список id вопросов.
    """
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS test_progress (
                user_id INTEGER,
                test_type INTEGER,
                idx INTEGER,
                q_ids TEXT,
                PRIMARY KEY (user_id, test_type)
            )
        ''')
        q_ids_str = ",".join(map(str, q_ids))
        c.execute('''
            INSERT OR REPLACE INTO test_progress (user_id, test_type, idx, q_ids)
            VALUES (?, ?, ?, ?)
        ''', (user_id, test_type, idx, q_ids_str))
        conn.commit()

def load_test_progress(user_id, test_type):
    """
    Возвращает (idx, q_ids) — номер текущего вопроса и список id вопросов, если пользователь уже проходил этот тест.
    Если не найдено — возвращает (None, None).
    """
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute('SELECT idx, q_ids FROM test_progress WHERE user_id=? AND test_type=?', (user_id, test_type))
        row = c.fetchone()
        if row:
            idx, q_ids_str = row
            q_ids = [int(qid) for qid in q_ids_str.split(',')]
            return idx, q_ids
        return None, None

def clear_test_progress(user_id, test_type):
    """
    Очищает прогресс прохождения теста (когда пользователь начинает заново).
    """
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute('DELETE FROM test_progress WHERE user_id=? AND test_type=?', (user_id, test_type))
        conn.commit()

def init_progress_table():
    """
    Создаёт таблицу для хранения прогресса тестов, если она ещё не создана.
    """
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS test_progress (
                user_id INTEGER,
                test_type INTEGER,
                idx INTEGER,
                q_ids TEXT,
                PRIMARY KEY (user_id, test_type)
            )
        ''')
        conn.commit()

# ========================
#   РАБОТА НАД ОШИБКАМИ
# ========================

def get_mistake_questions(user_id):
    """
    Возвращает список кортежей (test_type, question_id, question_text, user_answer, correct_answer)
    для всех ошибочных заданий пользователя (is_correct=0).
    """
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute("""
            SELECT test_type, question_id, question_text, user_answer, correct_answer
            FROM test_answers
            WHERE user_id=? AND is_correct=0
        """, (user_id,))
        return c.fetchall()

def set_answer_correct(user_id, question_id):
    """
    Помечает ошибку как исправленную (is_correct=1) для user_id и question_id.
    """
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute("""
            UPDATE test_answers SET is_correct=1 WHERE user_id=? AND question_id=?
        """, (user_id, question_id))
        conn.commit()

# ========================
#   ЛОГИРОВАНИЕ ВРЕМЕНИ НАЧАЛА ВОПРОСА И ОТВЕТА (НОВЫЙ ФУНКЦИОНАЛ)
# ========================

def init_activity_table():
    """
    Создаёт таблицу для логирования активности по вопросам: кто когда начал решать, когда ответил и с каким результатом.
    """
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS test_activity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                test_type INTEGER,
                question_id INTEGER,
                started_at TEXT,
                answered_at TEXT,
                user_answer TEXT,
                is_correct INTEGER
            )
        ''')
        conn.commit()

def log_question_started(user_id, test_type, question_id):
    """
    Логируем начало показа вопроса пользователю: user_id, test_type, question_id, started_at=now.
    Остальные поля NULL (ответа пока нет).
    """
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute('''
            INSERT INTO test_activity
            (user_id, test_type, question_id, started_at)
            VALUES (?, ?, ?, ?)
        ''', (
            user_id,
            test_type,
            question_id,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ))
        conn.commit()

def log_question_answered(user_id, question_id, user_answer, is_correct):
    """
    Когда пользователь ответил — обновляем запись: answered_at, user_answer, is_correct
    (ищем по user_id, question_id и answered_at IS NULL).
    """
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute('''
            UPDATE test_activity
            SET answered_at=?, user_answer=?, is_correct=?
            WHERE user_id=? AND question_id=? AND answered_at IS NULL
        ''', (
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            user_answer,
            int(is_correct),
            user_id,
            question_id
        ))
        conn.commit()

# ========================
#   СОХРАНЕНИЕ ОТВЕТОВ ПО ТЕОРИИ
# ========================

def save_theory_task_answer(
    user_id: int,
    username: str,
    topic: str,
    chunk_idx: int,
    question_index: int,
    question_text: str,
    answer_text: str,
    answer_type: str,
    voice_file_id: str | None = None,
    is_correct: bool | None = None,
    feedback: str | None = None,
):
    """Сохраняет ответ ученика на вопрос из раздела теории.

    answer_type: "text" или "voice"
    voice_file_id: file_id голосового (если есть)
    """
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute(
            '''INSERT INTO theory_task_answers
               (user_id, username, topic, chunk_idx, question_index, question_text, answer_text, answer_type, voice_file_id, is_correct, feedback, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (
                user_id,
                username,
                topic,
                int(chunk_idx),
                int(question_index),
                question_text,
                answer_text or "",
                answer_type,
                voice_file_id,
                int(is_correct) if is_correct is not None else None,
                feedback or "",
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
        conn.commit()


def get_theory_stats(user_id: int, topic: str) -> tuple[int, int]:
    """Возвращает (correct, total) по ответам ученика в теории для указанной темы.
    Учитываются только ответы, где is_correct не NULL.
    """
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute(
            """
            SELECT 
                SUM(CASE WHEN is_correct=1 THEN 1 ELSE 0 END) AS correct_cnt,
                COUNT(*) AS total_cnt
            FROM theory_task_answers
            WHERE user_id=? AND topic=? AND is_correct IS NOT NULL
            """,
            (user_id, topic),
        )
        row = c.fetchone() or (0, 0)
        correct, total = row[0] or 0, row[1] or 0
        return int(correct), int(total)
