import sqlite3
from typing import List, Dict, Any
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


def get_all_students_with_plans() -> List[Dict[str, Any]]:
    """
    Возвращает список ВСЕХ учеников с их текущими тарифами.
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
            
            # Получаем ВСЕХ пользователей с их тарифами
            govr_cur.execute("SELECT user_id, plan_code FROM user_plans")
            user_plans = {row[0]: row[1] for row in govr_cur.fetchall()}
        
        # Теперь получаем информацию о пользователях из prepod_bot
        with sqlite3.connect(DB_PATH) as prepod_conn:
            # Получаем учеников из user_profiles
            cur = prepod_conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_profiles (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    full_name TEXT,
                    created_at TEXT,
                    hide_reason TEXT
                )
            """)
            
            # Получаем всех учеников из user_profiles (не скрытых)
            cur.execute("SELECT user_id, username, full_name FROM user_profiles")
            profile_students = cur.fetchall()
            
            # Добавляем учеников из user_profiles
            for user_id, username, full_name in profile_students:
                label = full_name or username or f"ID {user_id}"
                plan_code = user_plans.get(user_id, 'free')
                
                student_data = {
                    "user_id": user_id,
                    "full_name": full_name,
                    "username": username,
                    "label": label,
                    "plan_code": plan_code,
                    "plan_name": _get_plan_name(plan_code)
                }
                
                students.append(student_data)
            
            # Если нет учеников в user_profiles, получаем из get_all_students()
            if not students:
                all_prepod_students = get_all_students()
                for student in all_prepod_students:
                    user_id = student["user_id"]
                    plan_code = user_plans.get(user_id, 'free')
                    
                    student["plan_code"] = plan_code
                    student["plan_name"] = _get_plan_name(plan_code)
                    
                    students.append(student)
    
    except Exception as e:
        print(f"Ошибка при получении учеников с тарифами: {e}")
        # Fallback: возвращаем всех учеников с тарифом 'free'
        all_students = get_all_students()
        for student in all_students:
            student["plan_code"] = 'free'
            student["plan_name"] = 'Бесплатный'
            students.append(student)
    
    # Сортируем по имени
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
