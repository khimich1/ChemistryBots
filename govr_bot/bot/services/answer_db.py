import os
import sqlite3
from datetime import datetime, date, timedelta

# Единая БД ответов в корне проекта: ChemistryBots/shared/test_answers.db
_THIS_DIR = os.path.dirname(__file__)  # govr_bot/bot/services
_PROJECT_ROOT = os.path.normpath(os.path.join(_THIS_DIR, "..", "..", ".."))
DB_FILE = os.getenv("DB_ANSWERS") or os.path.join(_PROJECT_ROOT, "shared", "test_answers.db")
  # Имя файла с базой данных

# 1. Создаём таблицу ответов (вызывается один раз при запуске)
def init_db():
    """
    Инициализация/миграции БД:
      - test_answers (добавляем столбец full_name при необходимости)
      - user_profiles (храним ФИО, чтобы не спрашивать каждый раз)
      - test_activity
      - test_debug (жалобы на вопросы)
    """
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        # Основная таблица ответов
        c.execute('''
            CREATE TABLE IF NOT EXISTS test_answers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT,
                full_name TEXT,
                answer_time TEXT,
                test_type INTEGER,
                question_id INTEGER,
                question_text TEXT,
                user_answer TEXT,
                correct_answer TEXT,
                is_correct INTEGER
            )
        ''')
        # Если таблица уже существовала без full_name — добавим
        c.execute("PRAGMA table_info(test_answers)")
        cols = {row[1] for row in c.fetchall()}
        if "full_name" not in cols:
            c.execute("ALTER TABLE test_answers ADD COLUMN full_name TEXT")
        # Профили пользователей: user_id -> username, full_name
        c.execute('''
            CREATE TABLE IF NOT EXISTS user_profiles (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                created_at TEXT
            )
        ''')
        conn.commit()
        # --- Таблица жалоб по вопросам ---
        c.execute('''
            CREATE TABLE IF NOT EXISTS test_debug (
                question_id INTEGER PRIMARY KEY,
                reason TEXT,
                status TEXT DEFAULT 'не решено'
            )
        ''')
        conn.commit()
        # --- Источники (deep-links) пользователей ---
        c.execute('''
            CREATE TABLE IF NOT EXISTS acquisition (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                start_param TEXT,
                first_seen_at TEXT,
                subscribed_at TEXT
            )
        ''')
        conn.commit()
        # --- Прогресс по карточкам (что пользователь уже видел) ---
        c.execute('''
            CREATE TABLE IF NOT EXISTS flashcards_seen (
                user_id INTEGER,
                category TEXT,
                card_key TEXT,
                first_seen_at TEXT,
                PRIMARY KEY (user_id, category, card_key)
            )
        ''')
        conn.commit()
        # --- Ошибки практики по карточкам ---
        c.execute('''
            CREATE TABLE IF NOT EXISTS flashcards_errors (
                user_id INTEGER,
                category TEXT,
                card_key TEXT,
                formula TEXT,
                expected_variants TEXT,
                added_at TEXT,
                PRIMARY KEY (user_id, category, card_key)
            )
        ''')
        conn.commit()
        # --- Лог ответов практики по карточкам (для аудио/текста) ---
        c.execute('''
            CREATE TABLE IF NOT EXISTS flashcards_practice_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                category TEXT,
                card_key TEXT,
                formula TEXT,
                answer_text TEXT,
                source TEXT,          -- 'text' | 'voice'
                is_correct INTEGER,
                created_at TEXT
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


# ========================
#   DEEP-LINK ACQUISITION
# ========================

def log_start_param(user_id: int, username: str | None, start_param: str | None) -> None:
    """Сохраняет метку из /start <param>.

    Правила:
    - если записи нет — создаём с переданной меткой (может быть пустой).
    - если запись есть и там пустая метка, а новая непустая — обновляем метку.
    - всегда обновляем username.
    """
    start_param = (start_param or "").strip()
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        # 1) Вставим запись при первом контакте
        c.execute(
            '''INSERT INTO acquisition (user_id, username, start_param, first_seen_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET username=excluded.username''',
            (user_id, username, start_param, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )
        # 2) Если старая метка пустая, а новая непустая — обновим
        if start_param:
            c.execute(
                '''UPDATE acquisition
                   SET start_param = ?
                 WHERE user_id = ? AND (TRIM(COALESCE(start_param,'')) = '')''',
                (start_param, user_id),
            )
        conn.commit()


def mark_subscribed(user_id: int) -> None:
    """Отмечает момент подтверждённой подписки пользователя."""
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute(
            '''UPDATE acquisition SET subscribed_at=? WHERE user_id=?''',
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), user_id),
        )
        conn.commit()

# 2. Запись одного ответа в таблицу test_answers
def save_test_answer(user_id, username, test_type, question_id, question_text, user_answer, correct_answer, is_correct, *, full_name: str | None = None):
    """
    Сохраняем ответ. Поле full_name берём из аргумента или, если не передано,
    пробуем подтянуть из user_profiles.
    """
    if full_name is None:
        full_name = get_user_full_name(user_id)
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute('''
            INSERT INTO test_answers
            (user_id, username, full_name, answer_time, test_type, question_id, question_text, user_answer, correct_answer, is_correct)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            user_id,
            username,
            full_name,
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

def reset_test_results(user_id: int, test_type: int) -> None:
    """
    Полный сброс результатов по тесту для пользователя:
    - удаляем ответы из test_answers
    - удаляем логи активности из test_activity
    """
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute("DELETE FROM test_answers WHERE user_id=? AND test_type=?", (user_id, test_type))
        c.execute("DELETE FROM test_activity WHERE user_id=? AND test_type=?", (user_id, test_type))
        conn.commit()

def get_last_results_for_questions(user_id: int, test_type: int, q_ids: list[int]) -> dict[int, int | None]:
    """
    Возвращает отображение question_id -> last_is_correct (1/0/None) для списка q_ids.

    Берём последнее по id запись в таблице test_answers для каждого вопроса.
    Если ответов не было — ключа может не быть в словаре.
    """
    if not q_ids:
        return {}
    placeholders = ",".join(["?"] * len(q_ids))
    params = [user_id, test_type, *[int(q) for q in q_ids]]
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute(
            f"""
            SELECT question_id, is_correct, id
            FROM test_answers
            WHERE user_id=? AND test_type=? AND question_id IN ({placeholders})
            ORDER BY id
            """,
            params,
        )
        result: dict[int, int | None] = {}
        for q_id, is_correct, _row_id in c.fetchall():
            result[int(q_id)] = None if is_correct is None else int(is_correct)
        return result

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

# ========================
#   ПРОФИЛЬ ПОЛЬЗОВАТЕЛЯ
# ========================

def get_user_full_name(user_id: int) -> str | None:
    """Возвращает сохранённое ФИО пользователя (если есть)."""
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute("SELECT COALESCE(NULLIF(TRIM(full_name), ''), NULL) FROM user_profiles WHERE user_id=?", (user_id,))
        row = c.fetchone()
        return row[0] if row else None


def set_user_full_name(user_id: int, username: str | None, full_name: str) -> None:
    """Сохраняет/обновляет ФИО пользователя в таблице user_profiles."""
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute('''
            INSERT INTO user_profiles (user_id, username, full_name, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET username=excluded.username, full_name=excluded.full_name
        ''', (
            user_id,
            username,
            full_name,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ))
        conn.commit()

# ========================
#   MOTIVATION MESSAGES
# ========================

def get_random_motivation_text() -> str | None:
    """Возвращает случайный текст из таблицы chem_motivation внутри основной БД.

    Ожидается таблица `chem_motivation` со столбцом `text` в файле БД
    `shared/test_answers.db`. Если таблицы нет — возвращает None и не падает.
    """
    try:
        with sqlite3.connect(DB_FILE) as conn:
            c = conn.cursor()
            c.execute("SELECT text FROM chem_motivation ORDER BY RANDOM() LIMIT 1")
            row = c.fetchone()
            if row and row[0]:
                return str(row[0])
            return None
    except sqlite3.OperationalError:
        return None


def get_user_activity_stats(user_id: int) -> tuple[int, int]:
    """
    Возвращает (streak_days, last7_active_days).

    streak_days — текущая серия активных дней подряд, считая сегодня.
    last7_active_days — количество дней с активностью за последние 7 дней (включая сегодня).

    Под активностью считаем наличие записей в:
      - test_answers (answer_time)
      - theory_task_answers (created_at)
      - flashcards_practice_log (created_at)
    """
    days: set[str] = set()
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        try:
            for table, col in (
                ("test_answers", "answer_time"),
                ("theory_task_answers", "created_at"),
                ("flashcards_practice_log", "created_at"),
            ):
                try:
                    c.execute(
                        f"SELECT DISTINCT substr({col},1,10) FROM {table} WHERE user_id=?",
                        (user_id,),
                    )
                    for (d,) in c.fetchall():
                        if d:
                            days.add(str(d))
                except Exception:
                    # Если таблицы нет — игнорируем
                    pass
        except Exception:
            pass

    # Преобразуем в множество дат
    have: set[date] = set()
    for d in days:
        try:
            y, m, dd = map(int, d.split("-"))
            have.add(date(y, m, dd))
        except Exception:
            continue

    today = date.today()
    # streak: текущая серия, начиная с сегодня
    streak = 0
    for i in range(0, 400):
        day = today - timedelta(days=i)
        if day in have:
            streak += 1
        else:
            break

    # last7: количество активных дней за последние 7
    last7 = 0
    for i in range(0, 7):
        if (today - timedelta(days=i)) in have:
            last7 += 1

    return streak, last7

# ========================
#   ПРОГРЕСС ПО КАРТОЧКАМ
# ========================

def flashcards_mark_seen(user_id: int, category: str, card_key: str) -> None:
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute('''
            INSERT OR IGNORE INTO flashcards_seen (user_id, category, card_key, first_seen_at)
            VALUES (?, ?, ?, ?)
        ''', (user_id, category, card_key, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()

def flashcards_get_seen_set(user_id: int, category: str) -> set[str]:
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute('SELECT card_key FROM flashcards_seen WHERE user_id=? AND category=?', (user_id, category))
        return {row[0] for row in c.fetchall()}

def flashcards_reset_category(user_id: int, category: str) -> None:
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute('DELETE FROM flashcards_seen WHERE user_id=? AND category=?', (user_id, category))
        conn.commit()

# ========================
#   ОШИБКИ ПРАКТИКИ КАРТОЧЕК
# ========================

def flashcards_add_error(user_id: int, category: str, card_key: str, formula: str, expected_variants: str) -> None:
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute('''
            INSERT OR REPLACE INTO flashcards_errors (user_id, category, card_key, formula, expected_variants, added_at)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (user_id, category, card_key, formula, expected_variants, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()

def flashcards_remove_error(user_id: int, category: str, card_key: str) -> None:
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute('DELETE FROM flashcards_errors WHERE user_id=? AND category=? AND card_key=?', (user_id, category, card_key))
        conn.commit()

def flashcards_list_errors(user_id: int, category: str) -> list[tuple[str, str, str]]:
    """Возвращает список (card_key, formula, expected_variants)"""
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute('SELECT card_key, formula, expected_variants FROM flashcards_errors WHERE user_id=? AND category=? ORDER BY added_at', (user_id, category))
        return [(row[0], row[1], row[2]) for row in c.fetchall()]


def flashcards_log_answer(user_id: int, category: str, card_key: str | None, formula: str | None, answer_text: str, source: str, is_correct: bool) -> None:
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute('''
            INSERT INTO flashcards_practice_log (user_id, category, card_key, formula, answer_text, source, is_correct, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, category, card_key or "", formula or "", answer_text or "", source, int(is_correct), datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()

def flashcards_last_transcript(user_id: int) -> tuple[str, str, str, str] | None:
    """Возвращает последний лог (category, card_key, formula, answer_text) пользователя."""
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute('''
            SELECT category, card_key, formula, answer_text
            FROM flashcards_practice_log
            WHERE user_id=?
            ORDER BY id DESC
            LIMIT 1
        ''', (user_id,))
        row = c.fetchone()
        if row:
            return row[0], row[1], row[2], row[3]
        return None

def flashcards_count_wrong_voice_attempts(user_id: int, category: str, card_key: str) -> int:
    """Возвращает количество неверных голосовых попыток по карточке."""
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute(
            '''SELECT COUNT(*) FROM flashcards_practice_log
               WHERE user_id=? AND category=? AND card_key=? AND source='voice' AND is_correct=0''',
            (user_id, category, card_key),
        )
        row = c.fetchone()
        return int(row[0] if row and row[0] is not None else 0)

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
#   ЖАЛОБЫ НА ВОПРОСЫ (test_debug)
# ========================

def save_test_debug(question_id: int, reason: str, status: str = "не решено") -> None:
    """Сохраняет/обновляет жалобу по вопросу в таблицу test_debug.

    Поля:
      - question_id: ID вопроса из таблицы tests
      - reason: причина жалобы (вариант, выбранный в боте, либо свободный текст)
      - status: 'решено' | 'не решено' (по умолчанию 'не решено')
    """
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute(
            '''
            INSERT INTO test_debug (question_id, reason, status)
            VALUES (?, ?, ?)
            ON CONFLICT(question_id) DO UPDATE SET reason=excluded.reason, status=excluded.status
            ''',
            (int(question_id), reason or "", status or "не решено"),
        )
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
