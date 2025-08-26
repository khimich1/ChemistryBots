#!/usr/bin/env python3
"""
Скрипт для добавления тестовых учеников в shared базу данных
"""

import sqlite3
import os

def add_test_students_shared():
    """Добавляет тестовых учеников в shared базу данных"""
    
    current_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Пути к базам данных
    shared_db = os.path.join(current_dir, "shared", "test_answers.db")
    govr_db = os.path.join(current_dir, "govr_bot", "bot", "services", "answers.db")
    
    print("👤 Добавление тестовых учеников в shared базу")
    print("=" * 50)
    print(f"📁 Shared база: {shared_db}")
    print(f"📁 Существует: {'✅' if os.path.exists(shared_db) else '❌'}")
    
    # Тестовые ученики
    test_students = [
        {"user_id": 1001, "username": "ivan_petrov", "full_name": "Иван Петров", "plan": "free"},
        {"user_id": 1002, "username": "maria_sidorova", "full_name": "Мария Сидорова", "plan": "group"},
        {"user_id": 1003, "username": "alex_kuznetsov", "full_name": "Алексей Кузнецов", "plan": "self"},
        {"user_id": 1004, "username": "anna_ivanova", "full_name": "Анна Иванова", "plan": "organic"},
        {"user_id": 1005, "username": "dmitry_smirnov", "full_name": "Дмитрий Смирнов", "plan": "elements"},
        {"user_id": 1006, "username": "elena_kuzmina", "full_name": "Елена Кузьмина", "plan": "full"},
    ]
    
    # 1. Добавляем в shared базу
    print("\n📝 Добавление в shared базу...")
    try:
        with sqlite3.connect(shared_db) as conn:
            cur = conn.cursor()
            
            # Создаем таблицу user_profiles
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_profiles (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    full_name TEXT,
                    created_at TEXT,
                    hide_reason TEXT
                )
            """)
            
            # Добавляем учеников
            for student in test_students:
                cur.execute("""
                    INSERT OR REPLACE INTO user_profiles (user_id, username, full_name, created_at)
                    VALUES (?, ?, ?, datetime('now'))
                """, (student["user_id"], student["username"], student["full_name"]))
            
            conn.commit()
            print(f"✅ Добавлено {len(test_students)} учеников в shared базу")
            
    except Exception as e:
        print(f"❌ Ошибка при добавлении в shared базу: {e}")
    
    # 2. Добавляем в govr_bot
    print("\n📝 Добавление в govr_bot...")
    try:
        with sqlite3.connect(govr_db) as conn:
            cur = conn.cursor()
            
            # Создаем таблицу user_plans
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_plans(
                    user_id INTEGER PRIMARY KEY,
                    plan_code TEXT,
                    started_at TEXT
                )
            """)
            
            # Добавляем учеников с тарифами
            for student in test_students:
                cur.execute("""
                    INSERT OR REPLACE INTO user_plans (user_id, plan_code, started_at)
                    VALUES (?, ?, datetime('now'))
                """, (student["user_id"], student["plan"]))
            
            conn.commit()
            print(f"✅ Добавлено {len(test_students)} учеников в govr_bot")
            
    except Exception as e:
        print(f"❌ Ошибка при добавлении в govr_bot: {e}")
    
    # 3. Показываем список добавленных учеников
    print("\n📋 Список добавленных учеников:")
    print("-" * 60)
    for student in test_students:
        plan_names = {
            'free': 'Бесплатный',
            'group': 'Групповой',
            'self': 'Самостоятельный',
            'organic': 'Органическая химия',
            'elements': 'Химия элементов',
            'full': 'Полный доступ'
        }
        plan_name = plan_names.get(student["plan"], student["plan"])
        print(f"👤 {student['full_name']} (@{student['username']}) - {plan_name}")
    
    print("\n" + "=" * 50)
    print("🏁 Добавление завершено!")

if __name__ == "__main__":
    add_test_students_shared()
