import sqlite3
import asyncio
from typing import List, Dict, Any
import os
from config import DB_PATH, TESTS_DB_EGE, TESTS_DB_OGE

# Переиспользуемый бот для govr-рассылок и простой троттлинг
_govr_bot_singleton = None
_govr_last_send_ts: float | None = None
_GOVR_SEND_MIN_INTERVAL = 0.035  # ~35ms между сообщениями (~28 msg/s), запас к лимитам
from services.students import get_all_students
from typing import Optional


def _project_root() -> str:
    """Возвращает абсолютный путь к корню репозитория ChemistryBots.
    Файл находится в prepod_bot/services → нужно подняться на три уровня до корня,
    где лежат папки prepod_bot, govr_bot и т.д.
    """
    return os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def _govr_db_path() -> str:
    """Абсолютный путь к БД govr-бота с ответами/тарифами."""
    repo_root = _project_root()
    return os.path.join(repo_root, "govr_bot", "bot", "services", "answers.db")


def _user_exists_anywhere(user_id: int) -> bool:
    """Проверяет наличие пользователя в ЛЮБОЙ из доступных баз:
    - prepod_bot: таблица test_answers (если есть)
    - govr_bot: таблица test_answers или user_plans (если есть)
    Возвращает True, если найден хотя бы где-то.
    """
    uid = int(user_id)
    # 1) prepod_bot DB_PATH
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            try:
                cur.execute("SELECT 1 FROM test_answers WHERE user_id = ? LIMIT 1", (uid,))
                if cur.fetchone():
                    return True
            except sqlite3.OperationalError:
                # таблицы может не быть — это ок
                pass
    except Exception:
        pass

    # 2) govr_bot answers.db
    try:
        gpath = _govr_db_path()
        with sqlite3.connect(gpath) as gconn:
            gcur = gconn.cursor()
            # test_answers
            try:
                gcur.execute("SELECT 1 FROM test_answers WHERE user_id = ? LIMIT 1", (uid,))
                if gcur.fetchone():
                    return True
            except sqlite3.OperationalError:
                pass
            # user_plans (учёт подписки)
            try:
                gcur.execute("SELECT 1 FROM user_plans WHERE user_id = ? LIMIT 1", (uid,))
                if gcur.fetchone():
                    return True
            except sqlite3.OperationalError:
                pass
    except Exception:
        pass

    return False


def _ensure_groups_table(conn: sqlite3.Connection) -> None:
    """Создает таблицу групп, если её нет"""
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS teacher_groups (
            user_id INTEGER PRIMARY KEY,
            added_at TEXT,
            teacher_id INTEGER
        )
        """
    )
    conn.commit()


def _ensure_work_groups_table(conn: sqlite3.Connection) -> None:
    """Создаёт таблицу рабочих групп, если её нет."""
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS work_groups (
            group_no INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            added_at TEXT,
            PRIMARY KEY (group_no, user_id)
        )
        """
    )
    # Добавим teacher_id колонку при необходимости (для фильтрации по преподавателю)
    try:
        cur.execute("PRAGMA table_info(work_groups)")
        cols = {row[1] for row in cur.fetchall()}
        if "teacher_id" not in cols:
            try:
                cur.execute("ALTER TABLE work_groups ADD COLUMN teacher_id INTEGER")
            except Exception:
                pass
    except Exception:
        pass
    conn.commit()


def _backfill_teacher_links(conn: sqlite3.Connection, teacher_id: int) -> None:
    """Проставляет teacher_id в старых записях (NULL) по эвристике:
    - work_groups: для всех пользователей, которые уже привязаны к преподавателю в teacher_groups
    - group_tasks: для всех наборов групп, где есть участники этого преподавателя
    """
    try:
        _ensure_groups_table(conn)
        _ensure_work_groups_table(conn)
        cur = conn.cursor()
        # 1) work_groups ← teacher_groups
        try:
            cur.execute(
                """
                UPDATE work_groups
                SET teacher_id = ?
                WHERE teacher_id IS NULL
                  AND user_id IN (
                    SELECT user_id FROM teacher_groups WHERE teacher_id = ?
                  )
                """,
                (int(teacher_id), int(teacher_id)),
            )
        except sqlite3.OperationalError:
            pass
        # 2) group_tasks ← work_groups
        try:
            cur.execute(
                """
                UPDATE group_tasks
                SET teacher_id = ?
                WHERE teacher_id IS NULL
                  AND group_no IN (
                    SELECT DISTINCT group_no FROM work_groups WHERE teacher_id = ?
                  )
                """,
                (int(teacher_id), int(teacher_id)),
            )
        except sqlite3.OperationalError:
            pass
        # 3) work_groups ← group_tasks (обратная синхронизация)
        try:
            cur.execute(
                """
                UPDATE work_groups
                SET teacher_id = ?
                WHERE teacher_id IS NULL
                  AND group_no IN (
                    SELECT DISTINCT group_no FROM group_tasks WHERE teacher_id = ?
                  )
                """,
                (int(teacher_id), int(teacher_id)),
            )
        except sqlite3.OperationalError:
            pass
        conn.commit()
    except Exception:
        # Тихо игнорируем — это вспомогательная миграция
        try:
            conn.rollback()
        except Exception:
            pass

def _ensure_group_tasks_table(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS group_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_no INTEGER NOT NULL,
            title TEXT NOT NULL,
            items TEXT NOT NULL,
            created_at TEXT
        )
        """
    )
    # Добавим teacher_id для приватности наборов по группам
    try:
        cur.execute("PRAGMA table_info(group_tasks)")
        cols = {row[1] for row in cur.fetchall()}
        if "teacher_id" not in cols:
            try:
                cur.execute("ALTER TABLE group_tasks ADD COLUMN teacher_id INTEGER")
            except Exception:
                pass
    except Exception:
        pass
    conn.commit()

def create_group_task(group_no: int, title: str, items_csv: str, *, teacher_id: int | None = None) -> int:
    """Создаёт набор заданий для группы. items_csv формат: "ege:1, oge:3, ege:5""" 
    with sqlite3.connect(DB_PATH) as conn:
        _ensure_group_tasks_table(conn)
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO group_tasks (group_no, title, items, created_at, teacher_id)
            VALUES (?, ?, ?, datetime('now','localtime'), ?)
            """,
            (group_no, title.strip(), items_csv.strip(), int(teacher_id) if teacher_id else None),
        )
        conn.commit()
        return int(cur.lastrowid)

def list_group_tasks(group_no: int, *, teacher_id: int | None = None) -> list[dict]:
    with sqlite3.connect(DB_PATH) as conn:
        _ensure_group_tasks_table(conn)
        if teacher_id is not None:
            _backfill_teacher_links(conn, int(teacher_id))
        cur = conn.cursor()
        if teacher_id is not None:
            try:
                cur.execute(
                    "SELECT id, title, items, created_at FROM group_tasks WHERE group_no=? AND teacher_id=? ORDER BY id DESC",
                    (group_no, int(teacher_id)),
                )
            except sqlite3.OperationalError as e:
                if "no such column: teacher_id" in str(e).lower():
                    try:
                        cur.execute("ALTER TABLE group_tasks ADD COLUMN teacher_id INTEGER")
                    except Exception:
                        pass
                    cur.execute(
                        "SELECT id, title, items, created_at FROM group_tasks WHERE group_no=? AND teacher_id=? ORDER BY id DESC",
                        (group_no, int(teacher_id)),
                    )
                else:
                    raise
        else:
            cur.execute(
                "SELECT id, title, items, created_at FROM group_tasks WHERE group_no=? ORDER BY id DESC",
                (group_no,),
            )
        rows = cur.fetchall()
    return [
        {"id": r[0], "title": r[1], "items": r[2], "created_at": r[3]}
        for r in rows
    ]

def delete_group_task(task_id: int) -> int | None:
    """Удаляет набор заданий по id.
    Возвращает номер группы, к которой принадлежал набор, либо None, если не найден.
    """
    with sqlite3.connect(DB_PATH) as conn:
        _ensure_group_tasks_table(conn)
        cur = conn.cursor()
        cur.execute("SELECT group_no FROM group_tasks WHERE id=?", (int(task_id),))
        row = cur.fetchone()
        if not row:
            return None
        group_no = int(row[0])
        cur.execute("DELETE FROM group_tasks WHERE id=?", (int(task_id),))
        conn.commit()
        return group_no

def get_group_task_by_id(task_id: int) -> dict | None:
    """Возвращает одну запись group_tasks по id или None."""
    with sqlite3.connect(DB_PATH) as conn:
        _ensure_group_tasks_table(conn)
        cur = conn.cursor()
        cur.execute(
            "SELECT id, group_no, title, items, created_at FROM group_tasks WHERE id=?",
            (int(task_id),),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {"id": int(row[0]), "group_no": int(row[1]), "title": row[2], "items": row[3], "created_at": row[4]}

def add_user_to_work_group(group_no: int, user_id: int, *, teacher_id: int | None = None) -> None:
    """Добавляет пользователя в рабочую группу."""
    with sqlite3.connect(DB_PATH) as conn:
        _ensure_work_groups_table(conn)
        cur = conn.cursor()
        sql = (
            """
            INSERT INTO work_groups (group_no, user_id, added_at, teacher_id)
            VALUES (?, ?, datetime('now','localtime'), ?)
            ON CONFLICT(group_no, user_id) DO UPDATE SET
                added_at = excluded.added_at,
                teacher_id = COALESCE(excluded.teacher_id, work_groups.teacher_id)
            """
        )
        params = (group_no, user_id, int(teacher_id) if teacher_id else None)
        try:
            cur.execute(sql, params)
        except sqlite3.OperationalError as e:
            # Миграция на лету: если нет колонки teacher_id — добавим и повторим вставку
            if "no such column: teacher_id" in str(e).lower():
                try:
                    cur.execute("ALTER TABLE work_groups ADD COLUMN teacher_id INTEGER")
                except Exception:
                    pass
                cur.execute(sql, params)
            else:
                raise
        conn.commit()


def get_work_group_members(group_no: int, *, teacher_id: int | None = None) -> List[int]:
    with sqlite3.connect(DB_PATH) as conn:
        _ensure_work_groups_table(conn)
        if teacher_id is not None:
            _backfill_teacher_links(conn, int(teacher_id))
        cur = conn.cursor()
        if teacher_id is not None:
            try:
                cur.execute("SELECT user_id FROM work_groups WHERE group_no = ? AND teacher_id=? ORDER BY user_id", (group_no, int(teacher_id)))
            except sqlite3.OperationalError as e:
                if "no such column: teacher_id" in str(e).lower():
                    try:
                        cur.execute("ALTER TABLE work_groups ADD COLUMN teacher_id INTEGER")
                    except Exception:
                        pass
                    cur.execute("SELECT user_id FROM work_groups WHERE group_no = ? AND teacher_id=? ORDER BY user_id", (group_no, int(teacher_id)))
                else:
                    raise
        else:
            cur.execute("SELECT user_id FROM work_groups WHERE group_no = ? ORDER BY user_id", (group_no,))
        return [row[0] for row in cur.fetchall()]


def remove_user_from_work_group(group_no: int, user_id: int) -> None:
    """Удаляет пользователя из рабочей группы."""
    with sqlite3.connect(DB_PATH) as conn:
        _ensure_work_groups_table(conn)
        cur = conn.cursor()
        cur.execute("DELETE FROM work_groups WHERE group_no=? AND user_id=?", (group_no, user_id))
        conn.commit()


def find_user_id_by_username(username: str) -> int | None:
    """Ищет user_id по username в базах prepod_bot (user_profiles, test_answers) и govr_bot."""
    uname = (username or "").strip()
    if uname.startswith("@"):
        uname = uname[1:]
    uname = uname.lower()

    # prepod_bot
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        try:
            cur.execute("SELECT user_id FROM user_profiles WHERE LOWER(NULLIF(TRIM(username),'')) = ? LIMIT 1", (uname,))
            row = cur.fetchone()
            if row:
                return int(row[0])
        except sqlite3.OperationalError:
            pass
        try:
            cur.execute(
                """
                SELECT user_id
                FROM test_answers
                WHERE LOWER(NULLIF(TRIM(username),'')) = ?
                ORDER BY answer_time DESC
                LIMIT 1
                """,
                (uname,),
            )
            row = cur.fetchone()
            if row:
                return int(row[0])
        except sqlite3.OperationalError:
            pass

    # govr_bot
    import os
    repo_root = _project_root()
    govr_db_file = os.path.join(repo_root, "govr_bot", "bot", "services", "answers.db")
    try:
        with sqlite3.connect(govr_db_file) as gconn:
            gcur = gconn.cursor()
            gcur.execute(
                """
                SELECT user_id
                FROM test_answers
                WHERE LOWER(NULLIF(TRIM(username),'')) = ?
                ORDER BY answer_time DESC
                LIMIT 1
                """,
                (uname,),
            )
            row = gcur.fetchone()
            if row:
                return int(row[0])
    except Exception:
        pass

    return None


def get_all_group_numbers() -> List[int]:
    """Возвращает все номера рабочих групп (уникальные, отсортированные)."""
    with sqlite3.connect(DB_PATH) as conn:
        _ensure_work_groups_table(conn)
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT group_no FROM work_groups ORDER BY group_no")
        return [int(row[0]) for row in cur.fetchall()]


async def broadcast_message_to_group_via_govr(group_no: int, text: str, *, teacher_id: int | None = None) -> tuple[int, int]:
    """Отправляет сообщение всем участникам группы через govr_bot.
    Требует переменной окружения GOVR_BOT_TOKEN (токен govr_bot).
    Возвращает (успешно, ошибок).
    """
    try:
        from aiogram import Bot
    except Exception:
        # aiogram точно есть, но если что — без отправки
        return 0, len(get_work_group_members(group_no))

    # Пытаемся вытащить токен govr-бота из разных имён переменных
    token = (
        os.getenv("BOT_TOKEN_govor")
        or os.getenv("BOT_TOKEN_GOVOR")
        or os.getenv("BOT_TOKEN_govr")
        or os.getenv("BOT_TOKEN_GOVR")
        or os.getenv("GOVR_BOT_TOKEN")
        or os.getenv("BOT_TOKEN")  # добавим основной токен
    )
    
    print(f"[DEBUG] broadcast: Переменные окружения: BOT_TOKEN={'***' if os.getenv('BOT_TOKEN') else 'НЕТ'}, "
          f"GOVR_BOT_TOKEN={'***' if os.getenv('GOVR_BOT_TOKEN') else 'НЕТ'}")
    
    if not token:
        print(f"[DEBUG] broadcast: Токен не найден в переменных окружения, проверяем .env файл")
        # Попробуем прочитать .env govr_bot и взять ключ BOT_TOKEN_govor / BOT_TOKEN
        try:
            from dotenv import dotenv_values
            repo_root = _project_root()
            env_path = os.path.join(repo_root, "govr_bot", ".env")
            print(f"[DEBUG] broadcast: Ищем .env по пути: {env_path}")
            if os.path.exists(env_path):
                vals = dotenv_values(env_path)
                print(f"[DEBUG] broadcast: .env файл найден, ключи: {list(vals.keys()) if vals else 'пустой'}")
                if vals:
                    token = (
                        vals.get("BOT_TOKEN_govor")
                        or vals.get("BOT_TOKEN_GOVOR")
                        or vals.get("BOT_TOKEN")
                    )
            else:
                print(f"[DEBUG] broadcast: .env файл НЕ найден по пути: {env_path}")
        except Exception as e:
            print(f"[DEBUG] broadcast: Ошибка при чтении .env: {e}")
            token = None

    print(f"[DEBUG] broadcast: Итоговый токен: {'***' if token else 'НЕ НАЙДЕН'}")
    
    if not token:
        return 0, len(get_work_group_members(group_no, teacher_id=teacher_id))

    user_ids = get_work_group_members(group_no, teacher_id=teacher_id)
    if not user_ids:
        return 0, 0
    # ленивое создание и переиспользование бота
    global _govr_bot_singleton
    if _govr_bot_singleton is None:
        _govr_bot_singleton = Bot(token=token)
    ok = 0
    fail = 0
    for uid in user_ids:
        try:
            # простой троттлинг (между сообщениями)
            try:
                import time
                global _govr_last_send_ts
                now = time.monotonic()
                if _govr_last_send_ts is not None:
                    delta = now - _govr_last_send_ts
                    if delta < _GOVR_SEND_MIN_INTERVAL:
                        await asyncio.sleep(_GOVR_SEND_MIN_INTERVAL - delta)
                _govr_last_send_ts = time.monotonic()
            except Exception:
                pass
            await _govr_bot_singleton.send_message(uid, text)
            ok += 1
        except Exception as e:
            # Попытаемся распознать FloodWait и подождать, затем продолжить
            try:
                from aiogram.exceptions import TelegramRetryAfter
                if isinstance(e, TelegramRetryAfter):
                    await asyncio.sleep(float(getattr(e, "retry_after", 1.0)))
                    try:
                        await _govr_bot_singleton.send_message(uid, text)
                        ok += 1
                        continue
                    except Exception:
                        pass
            except Exception:
                pass
            fail += 1
            continue
    return ok, fail


# ===============
# Notifications to a single user via govr_bot
# ===============

def _extract_username(target: str) -> Optional[str]:
    t = (target or "").strip()
    if not t:
        return None
    # Accept forms: @username, username, "Урок: @username", etc.
    if "@" in t:
        # take last token with @
        parts = [p for p in t.replace("\n", " ").split(" ") if p]
        for p in parts[::-1]:
            if p.startswith("@"):
                return p[1:]
    # if looks like username without @
    if t and t[0].isalnum():
        return t.lstrip("# ")
    return None


def resolve_user_id_from_target(target: str) -> Optional[int]:
    """Пытается получить user_id по полю target из занятия.
    Поддерживает варианты:
      - "@username"
      - "ID 123456"
      - произвольная подпись, содержащая @username
    Возвращает int или None.
    """
    # 1) Явный ID
    import re
    t = (target or "").strip()
    m = re.search(r"\bID\s*(\d+)\b", t, flags=re.IGNORECASE)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            pass
    # 2) Username
    uname = _extract_username(t)
    if uname:
        return find_user_id_by_username(uname)
    return None


async def send_message_to_user_via_govr(user_id: int, text: str) -> bool:
    """Отправляет одно сообщение пользователю через govr_bot. Возвращает True при успехе.
    Ищет токен так же, как broadcast_message_to_group_via_govr.
    """
    try:
        from aiogram import Bot
    except Exception:
        return False

    token = (
        os.getenv("BOT_TOKEN_govor")
        or os.getenv("BOT_TOKEN_GOVOR")
        or os.getenv("BOT_TOKEN_govr")
        or os.getenv("BOT_TOKEN_GOVR")
        or os.getenv("GOVR_BOT_TOKEN")
        or os.getenv("BOT_TOKEN")  # добавим основной токен
    )
    
    print(f"[DEBUG] Переменные окружения: BOT_TOKEN={'***' if os.getenv('BOT_TOKEN') else 'НЕТ'}, "
          f"GOVR_BOT_TOKEN={'***' if os.getenv('GOVR_BOT_TOKEN') else 'НЕТ'}")
    
    if not token:
        print(f"[DEBUG] Токен не найден в переменных окружения, проверяем .env файл")
        try:
            from dotenv import dotenv_values
            repo_root = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
            env_path = os.path.join(repo_root, "govr_bot", ".env")
            print(f"[DEBUG] Ищем .env по пути: {env_path}")
            if os.path.exists(env_path):
                vals = dotenv_values(env_path)
                print(f"[DEBUG] .env файл найден, ключи: {list(vals.keys()) if vals else 'пустой'}")
                if vals:
                    token = (
                        vals.get("BOT_TOKEN_govor")
                        or vals.get("BOT_TOKEN_GOVOR")
                        or vals.get("BOT_TOKEN")
                    )
            else:
                print(f"[DEBUG] .env файл НЕ найден по пути: {env_path}")
        except Exception as e:
            print(f"[DEBUG] Ошибка при чтении .env: {e}")
            token = None
    
    print(f"[DEBUG] Итоговый токен: {'***' if token else 'НЕ НАЙДЕН'}")
    
    if not token:
        print(f"[DEBUG] Токен не найден, отправка невозможна")
        return False

    # Проверка наличия пользователя в любой базе (prepod/govr)
    if not _user_exists_anywhere(int(user_id)):
        print(f"[DEBUG] Пользователь {user_id} не найден ни в одной базе, отправка невозможна")
        return False

    bot = Bot(token=token)
    try:
        print(f"[DEBUG] Отправляем сообщение user_id={user_id}: {text}")
        await bot.send_message(int(user_id), text)
        print(f"[DEBUG] Сообщение отправлено успешно")
        ok = True
    except Exception as e:
        print(f"[DEBUG] Ошибка отправки: {e}")
        ok = False
    try:
        await bot.session.close()
    except Exception:
        pass
    return ok

def get_all_students_with_plans() -> List[Dict[str, Any]]:
    """
    Возвращает список ВСЕХ учеников из get_all_students() и ДОБАВЛЯЕТ тарифы
    из govr_bot.user_plans. Это гарантирует, что поиск всегда увидит любого
    ученика, даже если его нет в user_profiles.
    """
    # Базовый список из prepod_bot
    students = get_all_students()

    # Чтение тарифов из govr_bot
    import os
    repo_root = _project_root()
    govr_db_file = os.path.join(repo_root, "govr_bot", "bot", "services", "answers.db")

    user_plans: Dict[int, str] = {}
    govr_users: Dict[int, Dict[str, Any]] = {}
    try:
        with sqlite3.connect(govr_db_file) as govr_conn:
            govr_cur = govr_conn.cursor()
            govr_cur.execute(
                """
                CREATE TABLE IF NOT EXISTS user_plans(
                    user_id INTEGER PRIMARY KEY,
                    plan_code TEXT,
                    started_at TEXT
                )
                """
            )
            govr_conn.commit()
            govr_cur.execute("SELECT user_id, plan_code FROM user_plans")
            user_plans = {int(row[0]): (row[1] or 'free') for row in govr_cur.fetchall()}

            # Дополнительно: попробуем достать имена из test_answers govr_bot
            try:
                govr_cur.execute(
                    """
                    SELECT DISTINCT user_id,
                           NULLIF(TRIM(username), ''),
                           NULLIF(TRIM(full_name), '')
                    FROM test_answers
                    WHERE NULLIF(TRIM(COALESCE(username, '')), '') <> ''
                       OR NULLIF(TRIM(COALESCE(full_name, '')), '') <> ''
                    """
                )
                for uid, uname, fname in govr_cur.fetchall():
                    try:
                        uid_int = int(uid)
                    except Exception:
                        continue
                    govr_users[uid_int] = {
                        "user_id": uid_int,
                        "username": uname,
                        "full_name": fname,
                        "label": (fname or uname or f"ID {uid_int}"),
                    }
            except Exception:
                pass
    except Exception as e:
        print(f"Ошибка при получении тарифов: {e}")
        user_plans = {}

    # Обогащаем данными о тарифе
    for s in students:
        plan_code = user_plans.get(int(s["user_id"]), 'free')
        s["plan_code"] = plan_code
        s["plan_name"] = _get_plan_name(plan_code)

    # Добавляем пользователей из govr_bot, которых не было в базе prepod_bot
    already = {int(s["user_id"]) for s in students}
    for uid, info in govr_users.items():
        if uid in already:
            # Обновим подпись, если у нас пусто
            for s in students:
                if int(s["user_id"]) == uid:
                    if not s.get("label"):
                        s["label"] = info.get("label")
                    if not s.get("username") and info.get("username"):
                        s["username"] = info.get("username")
                    if not s.get("full_name") and info.get("full_name"):
                        s["full_name"] = info.get("full_name")
                    break
        else:
            plan_code = user_plans.get(uid, 'free')
            students.append({
                "user_id": uid,
                "username": info.get("username"),
                "full_name": info.get("full_name"),
                "label": info.get("label") or f"ID {uid}",
                "plan_code": plan_code,
                "plan_name": _get_plan_name(plan_code),
            })

    students.sort(key=lambda s: str(s.get("label", "")))
    return students


def get_teacher_student_ids(teacher_id: int) -> List[int]:
    with sqlite3.connect(DB_PATH) as conn:
        _ensure_groups_table(conn)
        cur = conn.cursor()
        try:
            cur.execute("SELECT user_id FROM teacher_groups WHERE teacher_id=?", (int(teacher_id),))
            return [int(r[0]) for r in cur.fetchall()]
        except sqlite3.OperationalError:
            return []


def is_student_in_teacher_group(user_id: int, teacher_id: int) -> bool:
    with sqlite3.connect(DB_PATH) as conn:
        _ensure_groups_table(conn)
        cur = conn.cursor()
        try:
            cur.execute("SELECT 1 FROM teacher_groups WHERE user_id=? AND teacher_id=? LIMIT 1", (int(user_id), int(teacher_id)))
            return cur.fetchone() is not None
        except sqlite3.OperationalError:
            return False


def get_teacher_students_with_plans(teacher_id: int) -> List[Dict[str, Any]]:
    """Возвращает учеников текущего преподавателя (по teacher_groups) с тарифами."""
    all_students = get_all_students_with_plans()
    ids = set(get_teacher_student_ids(int(teacher_id)))
    return [s for s in all_students if int(s.get("user_id", 0)) in ids]


def _get_plan_name(plan_code: str) -> str:
    """Возвращает название тарифа на русском языке"""
    plan_names = {
        'free': 'Бесплатный',
        'group': 'Групповой',
        'self': 'Самостоятельный', 
        'organic': 'Органическая химия',
        'elements': 'Химия элементов',
        'full': 'Полный доступ'
    }
    return plan_names.get(plan_code, 'Бесплатный')


async def send_message_to_user_via_govr(user_id: int, text: str) -> bool:
    """Отправляет одиночное сообщение пользователю через govr_bot.
    Возвращает True при успехе.
    """
    try:
        from aiogram import Bot
    except Exception:
        return False

    token = (
        os.getenv("BOT_TOKEN_govor")
        or os.getenv("BOT_TOKEN_GOVOR")
        or os.getenv("BOT_TOKEN_govr")
        or os.getenv("BOT_TOKEN_GOVR")
        or os.getenv("GOVR_BOT_TOKEN")
    )

    if not token:
        # Попробуем прочитать .env govr_bot
        try:
            from dotenv import dotenv_values
            repo_root = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
            env_path = os.path.join(repo_root, "govr_bot", ".env")
            vals = dotenv_values(env_path)
            if vals:
                token = (
                    vals.get("BOT_TOKEN_govor")
                    or vals.get("BOT_TOKEN_GOVOR")
                    or vals.get("BOT_TOKEN")
                )
        except Exception:
            token = None

    if not token:
        return False

    bot = Bot(token=token)
    try:
        await bot.send_message(int(user_id), text)
        return True
    except Exception:
        return False
    finally:
        try:
            await bot.session.close()
        except Exception:
            pass


def get_students_with_group_access() -> List[Dict[str, Any]]:
    """
    Возвращает список учеников с подпиской 'group'.
    Использует базу данных govr_bot для получения информации о тарифах.
    """
    # Путь к базе данных govr_bot
    import os
    repo_root = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    
    # Получаем путь к базе govr_bot
    govr_db_file = os.path.join(repo_root, "govr_bot", "bot", "services", "answers.db")
    
    students = []
    
    try:
        # Подключаемся к базе govr_bot для получения тарифов
        with sqlite3.connect(govr_db_file) as govr_conn:
            govr_cur = govr_conn.cursor()
            
            # Создаем таблицу user_plans, если её нет
            govr_cur.execute(
                """
                CREATE TABLE IF NOT EXISTS user_plans(
                    user_id INTEGER PRIMARY KEY,
                    plan_code TEXT,
                    started_at TEXT
                )
                """
            )
            govr_conn.commit()
            
            # Получаем всех пользователей с тарифом 'group'
            govr_cur.execute("SELECT user_id FROM user_plans WHERE plan_code = 'group'")
            group_users = {row[0] for row in govr_cur.fetchall()}
        
        # Теперь получаем информацию о пользователях из prepod_bot
        with sqlite3.connect(DB_PATH) as prepod_conn:
            for user_id in group_users:
                # Получаем имя пользователя
                full_name, username = _get_user_identity(prepod_conn, user_id)
                label = full_name or username or f"ID {user_id}"
                
                students.append({
                    "user_id": user_id,
                    "full_name": full_name,
                    "username": username,
                    "label": label
                })
    
    except Exception as e:
        print(f"Ошибка при получении учеников с групповым доступом: {e}")
        # Fallback: возвращаем всех учеников
        students = get_all_students()
    
    # Сортируем по имени
    students.sort(key=lambda s: str(s.get("label", "")))
    return students


def _get_user_identity(conn: sqlite3.Connection, user_id: int) -> tuple:
    """Получает имя и username пользователя"""
    cur = conn.cursor()
    
    # Сначала пробуем из user_profiles
    cur.execute(
        "SELECT NULLIF(TRIM(full_name), ''), NULLIF(TRIM(username), '') FROM user_profiles WHERE user_id=?",
        (user_id,)
    )
    row = cur.fetchone()
    if row and (row[0] or row[1]):
        return row[0], row[1]
    
    # Затем из test_answers
    cur.execute(
        """
        SELECT NULLIF(TRIM(full_name), ''), NULLIF(TRIM(username), '')
        FROM test_answers
        WHERE user_id = ?
        ORDER BY answer_time DESC
        LIMIT 1
        """,
        (user_id,)
    )
    row = cur.fetchone()
    return row or (None, None)


def add_student_to_group(user_id: int, teacher_id: int = 1) -> None:
    """Добавляет ученика в группу преподавателя"""
    with sqlite3.connect(DB_PATH) as conn:
        _ensure_groups_table(conn)
        cur = conn.cursor()
        
        cur.execute(
            """
            INSERT INTO teacher_groups (user_id, added_at, teacher_id)
            VALUES (?, datetime('now', 'localtime'), ?)
            ON CONFLICT(user_id) DO UPDATE SET 
                added_at = datetime('now', 'localtime'),
                teacher_id = excluded.teacher_id
            """,
            (user_id, teacher_id)
        )
        conn.commit()


def remove_student_from_group(user_id: int) -> None:
    """Удаляет ученика из группы преподавателя"""
    with sqlite3.connect(DB_PATH) as conn:
        _ensure_groups_table(conn)
        cur = conn.cursor()
        
        cur.execute("DELETE FROM teacher_groups WHERE user_id = ?", (user_id,))
        conn.commit()


def is_student_in_group(user_id: int) -> bool:
    """Проверяет, находится ли ученик в группе преподавателя"""
    with sqlite3.connect(DB_PATH) as conn:
        _ensure_groups_table(conn)
        cur = conn.cursor()
        
        cur.execute("SELECT 1 FROM teacher_groups WHERE user_id = ?", (user_id,))
        return cur.fetchone() is not None


def get_group_students() -> List[Dict[str, Any]]:
    """Возвращает список всех учеников в группе"""
    with sqlite3.connect(DB_PATH) as conn:
        _ensure_groups_table(conn)
        cur = conn.cursor()
        
        cur.execute("SELECT user_id FROM teacher_groups")
        user_ids = [row[0] for row in cur.fetchall()]
    
    students = []
    for user_id in user_ids:
        # Получаем информацию о пользователе
        all_students = get_all_students()
        for student in all_students:
            if student["user_id"] == user_id:
                students.append(student)
                break
    
    return students


# =====================
# Helpers for selecting questions by variant (filename) or type
# =====================

def _tests_db_path_for(exam: str) -> str:
    """Возвращает путь к БД заданий для 'ege' или 'oge' из config.py."""
    exam_norm = (exam or "").strip().lower()
    if exam_norm == "oge":
        return TESTS_DB_OGE
    # default: ege
    return TESTS_DB_EGE


def _table_has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    try:
        cur = conn.cursor()
        cur.execute(f"PRAGMA table_info({table})")
        return any((row[1] == column) for row in cur.fetchall())
    except Exception:
        return False


def get_question_ids_by_type(exam: str, task_type: int, limit: int) -> List[int]:
    """Fetches question IDs by type from tests DB for specified exam.
    Skips questions marked has_issue when such column exists.
    """
    db_path = _tests_db_path_for(exam)
    ids: List[int] = []
    try:
        with sqlite3.connect(db_path) as conn:
            has_issue_col = _table_has_column(conn, "tests", "has_issue")
            # поддержка разных имён колонки типа
            type_col = None
            try:
                cur = conn.cursor()
                cur.execute("PRAGMA table_info(tests)")
                cols = {row[1] for row in cur.fetchall()}
                for name in ("type", "test_type", "theme", "task_type"):
                    if name in cols:
                        type_col = name
                        break
            except Exception:
                type_col = "type"
            if not type_col:
                type_col = "type"
            cur = conn.cursor()
            if has_issue_col:
                cur.execute(
                    """
                    SELECT id FROM tests
                    WHERE {tc}=? AND COALESCE(has_issue,0)=0
                    ORDER BY id
                    LIMIT ?
                    """.replace("{tc}", type_col),
                    (int(task_type), int(limit)),
                )
            else:
                cur.execute(
                    """
                    SELECT id FROM tests
                    WHERE {tc}=?
                    ORDER BY id
                    LIMIT ?
                    """.replace("{tc}", type_col),
                    (int(task_type), int(limit)),
                )
            ids = [int(r[0]) for r in cur.fetchall()]
    except Exception:
        ids = []
    return ids


def get_question_ids_by_filename(exam: str, filename: str) -> List[int]:
    """Fetches all question IDs that belong to the same variant (same tests.filename).
    If tests.filename column doesn't exist, returns empty list.
    Skips has_issue when present.
    """
    db_path = _tests_db_path_for(exam)
    fname = (filename or "").strip()
    if not fname:
        return []
    ids: List[int] = []
    try:
        with sqlite3.connect(db_path) as conn:
            if not _table_has_column(conn, "tests", "filename"):
                return []
            has_issue_col = _table_has_column(conn, "tests", "has_issue")
            # Определим имя колонки типа (type/test_type/theme/task_type)
            type_col = None
            try:
                cur = conn.cursor()
                cur.execute("PRAGMA table_info(tests)")
                cols = {row[1] for row in cur.fetchall()}
                for name in ("type", "test_type", "theme", "task_type"):
                    if name in cols:
                        type_col = name
                        break
            except Exception:
                type_col = "type"
            if not type_col:
                type_col = "type"
            cur = conn.cursor()
            if has_issue_col:
                cur.execute(
                    (
                        """
                        SELECT id FROM tests
                        WHERE filename=? AND COALESCE(has_issue,0)=0
                        ORDER BY {tc}, id
                        """
                    ).replace("{tc}", type_col),
                    (fname,),
                )
            else:
                cur.execute(
                    (
                        """
                        SELECT id FROM tests
                        WHERE filename=?
                        ORDER BY {tc}, id
                        """
                    ).replace("{tc}", type_col),
                    (fname,),
                )
            ids = [int(r[0]) for r in cur.fetchall()]
    except Exception:
        ids = []
    return ids


def list_variant_filenames(exam: str, limit: int = 300) -> List[str]:
    """Возвращает список уникальных значений tests.filename для выбранного экзамена.
    Если столбца filename нет — возвращает пустой список.
    """
    db_path = _tests_db_path_for(exam)
    names: List[str] = []
    try:
        with sqlite3.connect(db_path) as conn:
            if not _table_has_column(conn, "tests", "filename"):
                return []
            cur = conn.cursor()
            cur.execute(
                """
                SELECT DISTINCT filename
                FROM tests
                WHERE TRIM(COALESCE(filename,'')) <> ''
                ORDER BY filename
                LIMIT ?
                """,
                (int(limit),),
            )
            names = [str(r[0]) for r in cur.fetchall() if r and r[0]]
    except Exception:
        names = []
    return names


# =====================
#   Итоги по набору заданий группы
# =====================

def _parse_task_items_qids(items: str) -> list[int]:
    parts = [p.strip() for p in (items or "").split(",") if p.strip()]
    qids: list[int] = []
    for part in parts:
        try:
            _exam, sid = part.split(":", 1)
            qids.append(int(sid.strip()))
        except Exception:
            continue
    return qids


def compute_group_task_results(task_id: int) -> dict:
    """
    Возвращает словарь:
    {
      'group_no': int,
      'title': str,
      'qids': [int, ...],
      'results': [ { 'user_id': int, 'label': str, 'correct': int, 'total': int, 'pct': float }, ... ]
    }
    Считаем по последнему ответу на каждый вопрос из набора (таблица test_answers).
    """
    import sqlite3

    with sqlite3.connect(DB_PATH) as conn:
        # 1) сам набор
        _ensure_group_tasks_table(conn)
        cur = conn.cursor()
        cur.execute("SELECT group_no, title, items FROM group_tasks WHERE id=?", (int(task_id),))
        row = cur.fetchone()
        if not row:
            return {'group_no': None, 'title': '', 'qids': [], 'results': []}
        group_no, title, items = int(row[0]), str(row[1] or ''), str(row[2] or '')
        qids = _parse_task_items_qids(items)
        if not qids:
            return {'group_no': group_no, 'title': title, 'qids': [], 'results': []}

        # 2) участники группы
        members = get_work_group_members(group_no)
        results: list[dict] = []
        if not members:
            return {'group_no': group_no, 'title': title, 'qids': qids, 'results': []}

        placeholders = ",".join(["?"] * len(qids))
        sql = f"""
            SELECT question_id, is_correct, id
            FROM test_answers
            WHERE user_id=? AND question_id IN ({placeholders})
            ORDER BY id
        """

        for uid in members:
            # имя/username
            full_name, username = _get_user_identity(conn, int(uid))
            label = (full_name or username or f"ID {uid}")
            # берём последнюю запись по каждому question_id
            last: dict[int, int | None] = {int(q): None for q in qids}
            params = [int(uid), *[int(q) for q in qids]]
            try:
                cur.execute(sql, params)
                for qid, is_corr, _rid in cur.fetchall():
                    if qid in last:
                        last[int(qid)] = None if is_corr is None else int(is_corr)
            except sqlite3.OperationalError:
                # если таблицы нет — пусто
                pass
            correct = sum(1 for v in last.values() if v == 1)
            total = len(qids)
            pct = round((correct / total) * 100.0, 1) if total else 0.0
            results.append({'user_id': int(uid), 'label': label, 'correct': correct, 'total': total, 'pct': pct})

        # сортировка по убыванию верных, затем по имени
        results.sort(key=lambda r: (-r['correct'], str(r['label']).lower()))
        return {'group_no': group_no, 'title': title, 'qids': qids, 'results': results}


# =====================
# Async wrappers to offload blocking sqlite calls to a thread
# =====================

async def get_all_group_numbers_async() -> List[int]:
    return await asyncio.to_thread(get_all_group_numbers)


async def get_work_group_members_async(group_no: int, *, teacher_id: int | None = None) -> List[int]:
    return await asyncio.to_thread(get_work_group_members, group_no, teacher_id=teacher_id)


async def list_group_tasks_async(group_no: int, *, teacher_id: int | None = None) -> list[dict]:
    return await asyncio.to_thread(list_group_tasks, group_no, teacher_id=teacher_id)


async def create_group_task_async(group_no: int, title: str, items_csv: str, *, teacher_id: int | None = None) -> int:
    return await asyncio.to_thread(create_group_task, group_no, title, items_csv, teacher_id=teacher_id)


async def compute_group_task_results_async(task_id: int) -> dict:
    return await asyncio.to_thread(compute_group_task_results, task_id)


async def find_user_id_by_username_async(username: str) -> int | None:
    return await asyncio.to_thread(find_user_id_by_username, username)