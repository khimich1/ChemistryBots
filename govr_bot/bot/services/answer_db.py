import os
import sqlite3
from datetime import datetime, date, timedelta
from bot.utils_pkg_new.logger import log_error, log_database_operation
import threading
from contextlib import contextmanager

# Единая БД ответов в корне проекта: ChemistryBots/shared/test_answers.db
_THIS_DIR = os.path.dirname(__file__)  # govr_bot/bot/services
_PROJECT_ROOT = os.path.normpath(os.path.join(_THIS_DIR, "..", "..", ".."))
DB_FILE = os.getenv("DB_ANSWERS") or os.path.join(_PROJECT_ROOT, "shared", "test_answers.db")
  # Имя файла с базой данных

# Пул соединений для высокой нагрузки
_connection_pool = {}
_pool_lock = threading.Lock()

def get_conn():
    """Централизованное подключение к БД с пулом соединений для стабильности под нагрузкой."""
    thread_id = threading.get_ident()
    
    with _pool_lock:
        if thread_id not in _connection_pool:
            conn = sqlite3.connect(DB_FILE, timeout=10.0, isolation_level=None)
            c = conn.cursor()
            try:
                c.execute("PRAGMA journal_mode=WAL")
                c.execute("PRAGMA synchronous=NORMAL")
                c.execute("PRAGMA foreign_keys=ON")
                c.execute("PRAGMA busy_timeout=10000")
                c.execute("PRAGMA cache_size=10000")  # Увеличиваем кэш
                c.execute("PRAGMA temp_store=MEMORY")  # Временные таблицы в памяти
            finally:
                c.close()
            _connection_pool[thread_id] = conn
        return _connection_pool[thread_id]

@contextmanager
def get_db_connection():
    """Контекстный менеджер для безопасной работы с БД."""
    conn = get_conn()
    try:
        yield conn
    except Exception as e:
        log_error(e, "Database operation failed")
        raise

def close_all_connections():
    """Закрывает все соединения в пуле (вызывать при завершении работы)"""
    with _pool_lock:
        for conn in _connection_pool.values():
            try:
                conn.close()
            except Exception:
                pass
        _connection_pool.clear()

# 1. Создаём таблицу ответов (вызывается один раз при запуске)
def init_db():
    """
    Инициализация/миграции БД:
      - test_answers (добавляем столбец full_name при необходимости)
      - user_profiles (храним ФИО, чтобы не спрашивать каждый раз)
      - test_activity
      - test_debug (жалобы на вопросы)
    """
    with get_conn() as conn:
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
        
        # --- Таблица участников розыгрыша ---  # Розыгрыш - закомментировано
        # c.execute('''  # Розыгрыш - закомментировано
        #     CREATE TABLE IF NOT EXISTS giveaway_participants (  # Розыгрыш - закомментировано
        #         user_id INTEGER PRIMARY KEY,  # Розыгрыш - закомментировано
        #         username TEXT,  # Розыгрыш - закомментировано
        #         full_name TEXT,  # Розыгрыш - закомментировано
        #         registered_at TEXT  # Розыгрыш - закомментировано
        #     )  # Розыгрыш - закомментировано
        # ''')  # Розыгрыш - закомментировано
        # conn.commit()  # Розыгрыш - закомментировано
        
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
    with get_conn() as conn:
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
    with get_conn() as conn:
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
    with get_conn() as conn:
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
    with get_conn() as conn:
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
    with get_conn() as conn:
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
    with get_conn() as conn:
        c = conn.cursor()
        c.execute('DELETE FROM test_progress WHERE user_id=? AND test_type=?', (user_id, test_type))
        conn.commit()

# === Прогресс групповых заданий ===

def _init_group_task_progress():
    with get_conn() as conn:
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS group_task_progress (
                user_id INTEGER,
                task_id INTEGER,
                current_question INTEGER,
                correct_answers INTEGER,
                items TEXT,
                title TEXT,
                updated_at TEXT,
                PRIMARY KEY (user_id, task_id)
            )
        ''')
        conn.commit()

def save_group_task_progress(user_id: int, task_id: int, current_question: int, correct_answers: int, items: str, title: str) -> None:
    _init_group_task_progress()
    with get_conn() as conn:
        c = conn.cursor()
        c.execute('''
            INSERT INTO group_task_progress (user_id, task_id, current_question, correct_answers, items, title, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, task_id) DO UPDATE SET
                current_question=excluded.current_question,
                correct_answers=excluded.correct_answers,
                items=excluded.items,
                title=excluded.title,
                updated_at=excluded.updated_at
        ''', (int(user_id), int(task_id), int(current_question), int(correct_answers or 0), items or "", title or "", datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()

def load_group_task_progress(user_id: int, task_id: int) -> tuple[int, int, str, str] | None:
    _init_group_task_progress()
    with get_conn() as conn:
        c = conn.cursor()
        c.execute('SELECT current_question, correct_answers, items, title FROM group_task_progress WHERE user_id=? AND task_id=?', (int(user_id), int(task_id)))
        row = c.fetchone()
        if row:
            cq, ca, items, title = row
            return int(cq or 0), int(ca or 0), str(items or ""), str(title or "")
        return None

def clear_group_task_progress(user_id: int, task_id: int) -> None:
    _init_group_task_progress()
    with get_conn() as conn:
        c = conn.cursor()
        c.execute('DELETE FROM group_task_progress WHERE user_id=? AND task_id=?', (int(user_id), int(task_id)))
        conn.commit()

def reset_test_results(user_id: int, test_type: int) -> None:
    """
    Полный сброс результатов по тесту для пользователя:
    - удаляем ответы из test_answers
    - удаляем логи активности из test_activity
    """
    with get_conn() as conn:
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
    with get_conn() as conn:
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
    with get_conn() as conn:
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
    with get_conn() as conn:
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
    with get_conn() as conn:
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
    with get_conn() as conn:
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
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT COALESCE(NULLIF(TRIM(full_name), ''), NULL) FROM user_profiles WHERE user_id=?", (user_id,))
        row = c.fetchone()
        return row[0] if row else None


def set_user_full_name(user_id: int, username: str | None, full_name: str) -> None:
    """Сохраняет/обновляет ФИО пользователя в таблице user_profiles."""
    with get_conn() as conn:
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
        with get_conn() as conn:
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
    with get_conn() as conn:
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
                except sqlite3.OperationalError as e:
                    # Таблицы нет или проблемы с БД
                    log_error(e, f"Database table {table} error for user {user_id}", user_id=user_id)
                    continue
                except sqlite3.Error as e:
                    # Другие ошибки SQLite
                    log_error(e, f"SQLite error in table {table} for user {user_id}", user_id=user_id)
                    continue
        except Exception as e:
            log_error(e, f"Unexpected error getting activity stats for user {user_id}", user_id=user_id)
            return 0, 0

    # Преобразуем в множество дат
    have: set[date] = set()
    for d in days:
        try:
            y, m, dd = map(int, d.split("-"))
            have.add(date(y, m, dd))
        except (ValueError, TypeError) as e:
            # Неправильный формат даты
            log_error(e, f"Invalid date format: {d} for user {user_id}", user_id=user_id)
            continue
        except Exception as e:
            # Неожиданные ошибки при парсинге даты
            log_error(e, f"Unexpected error parsing date {d} for user {user_id}", user_id=user_id)
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
    with get_conn() as conn:
        c = conn.cursor()
        c.execute('''
            INSERT OR IGNORE INTO flashcards_seen (user_id, category, card_key, first_seen_at)
            VALUES (?, ?, ?, ?)
        ''', (user_id, category, card_key, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()

def flashcards_get_seen_set(user_id: int, category: str) -> set[str]:
    with get_conn() as conn:
        c = conn.cursor()
        c.execute('SELECT card_key FROM flashcards_seen WHERE user_id=? AND category=?', (user_id, category))
        return {row[0] for row in c.fetchall()}

def flashcards_reset_category(user_id: int, category: str) -> None:
    with get_conn() as conn:
        c = conn.cursor()
        c.execute('DELETE FROM flashcards_seen WHERE user_id=? AND category=?', (user_id, category))
        conn.commit()

# ========================
#   ОШИБКИ ПРАКТИКИ КАРТОЧЕК
# ========================

def flashcards_add_error(user_id: int, category: str, card_key: str, formula: str, expected_variants: str) -> None:
    with get_conn() as conn:
        c = conn.cursor()
        c.execute('''
            INSERT OR REPLACE INTO flashcards_errors (user_id, category, card_key, formula, expected_variants, added_at)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (user_id, category, card_key, formula, expected_variants, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()

def flashcards_remove_error(user_id: int, category: str, card_key: str) -> None:
    with get_conn() as conn:
        c = conn.cursor()
        c.execute('DELETE FROM flashcards_errors WHERE user_id=? AND category=? AND card_key=?', (user_id, category, card_key))
        conn.commit()

def flashcards_list_errors(user_id: int, category: str) -> list[tuple[str, str, str]]:
    """Возвращает список (card_key, formula, expected_variants)"""
    with get_conn() as conn:
        c = conn.cursor()
        c.execute('SELECT card_key, formula, expected_variants FROM flashcards_errors WHERE user_id=? AND category=? ORDER BY added_at', (user_id, category))
        return [(row[0], row[1], row[2]) for row in c.fetchall()]


def flashcards_log_answer(user_id: int, category: str, card_key: str | None, formula: str | None, answer_text: str, source: str, is_correct: bool) -> None:
    with get_conn() as conn:
        c = conn.cursor()
        c.execute('''
            INSERT INTO flashcards_practice_log (user_id, category, card_key, formula, answer_text, source, is_correct, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, category, card_key or "", formula or "", answer_text or "", source, int(is_correct), datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()

def flashcards_last_transcript(user_id: int) -> tuple[str, str, str, str] | None:
    """Возвращает последний лог (category, card_key, formula, answer_text) пользователя."""
    with get_conn() as conn:
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
    with get_conn() as conn:
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
    with get_conn() as conn:
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
    with get_conn() as conn:
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
    with get_conn() as conn:
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
    with get_conn() as conn:
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
    """Возвращает (correct, total) по теме:
    - correct: число УНИКАЛЬНЫХ вопросов (topic+chunk_idx+question_index), на которые ученик ответил верно хотя бы раз
    - total: текущее число вопросов по теме в БД prepared_lectures (сумма по всем chunk'ам)

    Это устойчиво к ручным правкам количества вопросов в БД: total пересчитывается динамически.
    """
    # 1) correct — считаем уникальные правильные вопросы
    with get_conn() as conn:
        c = conn.cursor()
        c.execute(
            """
            SELECT COUNT(*) FROM (
                SELECT DISTINCT chunk_idx, question_index
                FROM theory_task_answers
                WHERE user_id=? AND topic=? AND is_correct=1
            ) t
            """,
            (user_id, topic),
        )
        row = c.fetchone()
        correct = int(row[0] if row and row[0] is not None else 0)

    # 2) total — берём из prepared_lectures сумму количества вопросов по теме
    try:
        # Ленивая и безопасная импорт-зависимость, чтобы не создавать циклы
        from bot.utils import PREPARED_LECTURES_DB
        from bot.utils import _parse_qa_field  # noqa: F401 (используем ниже)
        import sqlite3 as _sqlite
        total = 0
        with _sqlite.connect(PREPARED_LECTURES_DB) as conn2:
            c2 = conn2.cursor()
            try:
                c2.execute("SELECT qa_questions FROM prepared_lectures WHERE topic=?", (topic,))
            except _sqlite.OperationalError:
                total = 0
            else:
                for (raw,) in c2.fetchall():
                    # используем общий парсер для JSON/строк
                    from bot.utils import _parse_qa_field as _parse
                    total += len(_parse(raw))
        total = int(total)
    except Exception as e:
        log_error(e, f"Error getting theory stats total for user {user_id}, topic {topic}", user_id=user_id)
        total = 0

    return int(correct), int(total)


def get_theory_stats_by_chunk(user_id: int, topic: str) -> dict[int, tuple[int, int]]:
    """Возвращает словарь chunk_idx -> (correct, total) по теме.

    - correct — количество УНИКАЛЬНЫХ вопросов по этому chunk, на которые
      пользователь ответил верно хотя бы раз.
    - total   — текущее число вопросов в этом chunk (динамически из БД prepared_lectures).
    """
    # 1) correct по каждому chunk_idx
    correct_by_chunk: dict[int, int] = {}
    with get_conn() as conn:
        c = conn.cursor()
        try:
            c.execute(
                """
                SELECT chunk_idx, COUNT(DISTINCT question_index)
                FROM theory_task_answers
                WHERE user_id=? AND topic=? AND is_correct=1
                GROUP BY chunk_idx
                """,
                (user_id, topic),
            )
            for ch_idx, cnt in c.fetchall():
                try:
                    correct_by_chunk[int(ch_idx)] = int(cnt)
                except (ValueError, TypeError) as e:
                    log_error(e, f"Invalid chunk data for user {user_id}, topic {topic}", user_id=user_id)
                    continue
        except sqlite3.OperationalError as e:
            log_error(e, f"Database error getting theory stats for user {user_id}, topic {topic}", user_id=user_id)
        except sqlite3.Error as e:
            log_error(e, f"SQLite error getting theory stats for user {user_id}, topic {topic}", user_id=user_id)
        except Exception as e:
            log_error(e, f"Unexpected error getting theory stats for user {user_id}, topic {topic}", user_id=user_id)

    # 2) total по каждому chunk_idx — из prepared_lectures
    totals_by_chunk: dict[int, int] = {}
    try:
        from bot.utils import PREPARED_LECTURES_DB
        from bot.utils import _parse_qa_field as _parse
        import sqlite3 as _sqlite

        with _sqlite.connect(PREPARED_LECTURES_DB) as conn2:
            c2 = conn2.cursor()
            try:
                c2.execute(
                    "SELECT chunk_idx, qa_questions FROM prepared_lectures WHERE topic=?",
                    (topic,),
                )
            except _sqlite.OperationalError:
                totals_by_chunk = {}
            else:
                for ch_idx, raw in c2.fetchall():
                    try:
                        idx = int(ch_idx)
                        totals_by_chunk[idx] = len(_parse(raw))
                    except (ValueError, TypeError) as e:
                        log_error(e, f"Invalid chunk index for user {user_id}, topic {topic}", user_id=user_id)
                        continue
                    except Exception as e:
                        log_error(e, f"Error parsing chunk data for user {user_id}, topic {topic}", user_id=user_id)
                        continue
    except Exception as e:
        log_error(e, f"Error getting totals by chunk for user {user_id}, topic {topic}", user_id=user_id)
        totals_by_chunk = {}

    # 3) Объединяем
    result: dict[int, tuple[int, int]] = {}
    keys = set(totals_by_chunk.keys()) | set(correct_by_chunk.keys())
    for k in keys:
        result[int(k)] = (int(correct_by_chunk.get(k, 0)), int(totals_by_chunk.get(k, 0)))
    return result