#!/usr/bin/env python3
"""
Тестовый скрипт для проверки функционала групп
"""

import sqlite3
import os

def test_group_functionality():
    """Тестирует функционал групп"""
    
    # Пути к базам данных
    current_dir = os.path.dirname(os.path.abspath(__file__))
    prepod_db = os.path.join(current_dir, "prepod_bot", "test_answers.db")
    govr_db = os.path.join(current_dir, "govr_bot", "bot", "services", "answers.db")
    
    print("🧪 Тестирование функционала групп")
    print("=" * 50)
    
    # 1. Проверяем существование баз данных
    print(f"📁 База prepod_bot: {'✅' if os.path.exists(prepod_db) else '❌'} {prepod_db}")
    print(f"📁 База govr_bot: {'✅' if os.path.exists(govr_db) else '❌'} {govr_db}")
    
    # 2. Создаем тестового пользователя в govr_bot
    print("\n👤 Создание тестового пользователя...")
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
            
            # Добавляем тестового пользователя с тарифом 'group'
            test_user_id = 12345
            cur.execute("""
                INSERT OR REPLACE INTO user_plans (user_id, plan_code, started_at)
                VALUES (?, 'group', datetime('now'))
            """, (test_user_id,))
            
            conn.commit()
            print(f"✅ Тестовый пользователь {test_user_id} создан с тарифом 'group'")
            
    except Exception as e:
        print(f"❌ Ошибка при создании тестового пользователя: {e}")
        return
    
    # 3. Создаем тестового пользователя в prepod_bot
    print("\n👤 Создание тестового пользователя в prepod_bot...")
    try:
        with sqlite3.connect(prepod_db) as conn:
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
            
            # Добавляем тестового пользователя
            test_user_id = 12345
            cur.execute("""
                INSERT OR REPLACE INTO user_profiles (user_id, username, full_name, created_at)
                VALUES (?, 'test_user', 'Тестовый Ученик', datetime('now'))
            """, (test_user_id,))
            
            conn.commit()
            print(f"✅ Тестовый пользователь {test_user_id} создан в prepod_bot")
            
    except Exception as e:
        print(f"❌ Ошибка при создании пользователя в prepod_bot: {e}")
        return
    
    # 4. Тестируем добавление в группу
    print("\n👥 Тестирование добавления в группу...")
    try:
        with sqlite3.connect(prepod_db) as conn:
            cur = conn.cursor()
            
            # Создаем таблицу teacher_groups
            cur.execute("""
                CREATE TABLE IF NOT EXISTS teacher_groups (
                    user_id INTEGER PRIMARY KEY,
                    added_at TEXT,
                    teacher_id INTEGER
                )
            """)
            
            # Добавляем пользователя в группу
            test_user_id = 12345
            cur.execute("""
                INSERT OR REPLACE INTO teacher_groups (user_id, added_at, teacher_id)
                VALUES (?, datetime('now'), 1)
            """, (test_user_id,))
            
            conn.commit()
            print(f"✅ Пользователь {test_user_id} добавлен в группу")
            
    except Exception as e:
        print(f"❌ Ошибка при добавлении в группу: {e}")
        return
    
    # 5. Тестируем проверку доступа
    print("\n🔍 Тестирование проверки доступа...")
    try:
        # Импортируем функцию проверки доступа
        import sys
        sys.path.append(os.path.join(current_dir, "govr_bot", "bot", "services"))
        
        from teacher_access import get_group_access_status
        
        status = get_group_access_status(test_user_id)
        print(f"📊 Статус доступа для пользователя {test_user_id}:")
        print(f"   - Имеет групповой тариф: {status['has_group_plan']}")
        print(f"   - Одобрен преподавателем: {status['is_approved']}")
        print(f"   - Может получить доступ: {status['can_access']}")
        print(f"   - Текущий план: {status['current_plan']}")
        
        if status['can_access']:
            print("✅ Тест пройден! Пользователь имеет доступ к групповому тарифу")
        else:
            print("❌ Тест не пройден! Пользователь не имеет доступа")
            
    except Exception as e:
        print(f"❌ Ошибка при проверке доступа: {e}")
    
    print("\n" + "=" * 50)
    print("🏁 Тестирование завершено")

if __name__ == "__main__":
    test_group_functionality()
