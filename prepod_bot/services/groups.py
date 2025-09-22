import sqlite3
from typing import List, Dict, Any
import os
from config import DB_PATH
from services.students import get_all_students


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
    conn.commit()

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
    conn.commit()

def create_group_task(group_no: int, title: str, items_csv: str) -> int:
    """Создаёт набор заданий для группы. items_csv формат: "ege:1, oge:3, ege:5""" 
    with sqlite3.connect(DB_PATH) as conn:
        _ensure_group_tasks_table(conn)
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO group_tasks (group_no, title, items, created_at)
            VALUES (?, ?, ?, datetime('now','localtime'))
            """,
            (group_no, title.strip(), items_csv.strip()),
        )
        conn.commit()
        return int(cur.lastrowid)

def list_group_tasks(group_no: int) -> list[dict]:
    with sqlite3.connect(DB_PATH) as conn:
        _ensure_group_tasks_table(conn)
        cur = conn.cursor()
        cur.execute(
            "SELECT id, title, items, created_at FROM group_tasks WHERE group_no=? ORDER BY id DESC",
            (group_no,),
        )
        rows = cur.fetchall()
    return [
        {"id": r[0], "title": r[1], "items": r[2], "created_at": r[3]}
        for r in rows
    ]

def add_user_to_work_group(group_no: int, user_id: int) -> None:
    """Добавляет пользователя в рабочую группу."""
    with sqlite3.connect(DB_PATH) as conn:
        _ensure_work_groups_table(conn)
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO work_groups (group_no, user_id, added_at)
            VALUES (?, ?, datetime('now','localtime'))
            ON CONFLICT(group_no, user_id) DO UPDATE SET
                added_at = excluded.added_at
            """,
            (group_no, user_id),
        )
        conn.commit()


def get_work_group_members(group_no: int) -> List[int]:
    with sqlite3.connect(DB_PATH) as conn:
        _ensure_work_groups_table(conn)
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM work_groups WHERE group_no = ? ORDER BY user_id", (group_no,))
        return [row[0] for row in cur.fetchall()]


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
    repo_root = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
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


async def broadcast_message_to_group_via_govr(group_no: int, text: str) -> tuple[int, int]:
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
    )
    if not token:
        # Попробуем прочитать .env govr_bot и взять ключ BOT_TOKEN_govor / BOT_TOKEN
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
        return 0, len(get_work_group_members(group_no))

    user_ids = get_work_group_members(group_no)
    if not user_ids:
        return 0, 0

    bot = Bot(token=token)
    ok = 0
    fail = 0
    for uid in user_ids:
        try:
            await bot.send_message(uid, text)
            ok += 1
        except Exception:
            fail += 1
            continue
    try:
        await bot.session.close()
    except Exception:
        pass
    return ok, fail

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
    repo_root = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
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
