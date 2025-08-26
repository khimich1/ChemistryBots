import sqlite3
import os
from typing import Optional
from bot.services.answer_db import DB_FILE


def _get_prepod_db_path() -> str:
    """Получает путь к базе данных prepod_bot"""
    # Путь к базе prepod_bot относительно govr_bot
    current_dir = os.path.dirname(__file__)  # bot/services
    bot_dir = os.path.dirname(current_dir)   # bot
    govr_dir = os.path.dirname(bot_dir)      # govr_bot
    repo_root = os.path.dirname(govr_dir)    # ChemistryBots
    
    # Сначала пробуем shared базу данных
    shared_db = os.path.join(repo_root, "shared", "test_answers.db")
    if os.path.exists(shared_db):
        return shared_db
    
    # Если нет, используем prepod_bot базу
    prepod_dir = os.path.join(repo_root, "prepod_bot")
    prepod_db = os.path.join(prepod_dir, "test_answers.db")
    return prepod_db


def is_student_approved_by_teacher(user_id: int) -> bool:
    """
    Проверяет, одобрен ли ученик преподавателем для доступа к тарифу 'group'.
    
    Args:
        user_id: ID пользователя
        
    Returns:
        True, если ученик одобрен преподавателем
    """
    try:
        prepod_db_path = _get_prepod_db_path()
        
        if not os.path.exists(prepod_db_path):
            print(f"База данных prepod_bot не найдена: {prepod_db_path}")
            return False
        
        with sqlite3.connect(prepod_db_path) as conn:
            cur = conn.cursor()
            
            # Проверяем, существует ли таблица teacher_groups
            cur.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name='teacher_groups'
            """)
            
            if not cur.fetchone():
                # Таблица не существует, создаем её
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS teacher_groups (
                        user_id INTEGER PRIMARY KEY,
                        added_at TEXT,
                        teacher_id INTEGER
                    )
                """)
                conn.commit()
                return False
            
            # Проверяем, есть ли пользователь в группе
            cur.execute("SELECT 1 FROM teacher_groups WHERE user_id = ?", (user_id,))
            return cur.fetchone() is not None
            
    except Exception as e:
        print(f"Ошибка при проверке доступа преподавателя: {e}")
        return False


def can_access_group_tariff(user_id: int) -> bool:
    """
    Проверяет, может ли пользователь получить доступ к тарифу 'group'.
    
    Args:
        user_id: ID пользователя
        
    Returns:
        True, если пользователь может получить доступ к тарифу 'group'
    """
    # Сначала проверяем, есть ли у пользователя тариф 'group'
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cur = conn.cursor()
            
            # Создаем таблицу user_plans, если её нет
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_plans(
                    user_id INTEGER PRIMARY KEY,
                    plan_code TEXT,
                    started_at TEXT
                )
            """)
            conn.commit()
            
            # Проверяем тариф пользователя
            cur.execute("SELECT plan_code FROM user_plans WHERE user_id = ?", (user_id,))
            row = cur.fetchone()
            
            if not row or row[0] != 'group':
                return False
            
            # Если тариф 'group', проверяем одобрение преподавателя
            return is_student_approved_by_teacher(user_id)
            
    except Exception as e:
        print(f"Ошибка при проверке доступа к групповому тарифу: {e}")
        return False


def get_group_access_status(user_id: int) -> dict:
    """
    Возвращает статус доступа к групповому тарифу.
    
    Args:
        user_id: ID пользователя
        
    Returns:
        Словарь с информацией о статусе доступа
    """
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cur = conn.cursor()
            
            # Создаем таблицу user_plans, если её нет
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_plans(
                    user_id INTEGER PRIMARY KEY,
                    plan_code TEXT,
                    started_at TEXT
                )
            """)
            conn.commit()
            
            # Проверяем тариф пользователя
            cur.execute("SELECT plan_code FROM user_plans WHERE user_id = ?", (user_id,))
            row = cur.fetchone()
            
            current_plan = row[0] if row else 'free'
            has_group_plan = current_plan == 'group'
            is_approved = is_student_approved_by_teacher(user_id) if has_group_plan else False
            
            return {
                'has_group_plan': has_group_plan,
                'is_approved': is_approved,
                'current_plan': current_plan,
                'can_access': has_group_plan and is_approved
            }
            
    except Exception as e:
        print(f"Ошибка при получении статуса группового доступа: {e}")
        return {
            'has_group_plan': False,
            'is_approved': False,
            'current_plan': 'free',
            'can_access': False
        }
