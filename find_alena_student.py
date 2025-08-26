#!/usr/bin/env python3
"""
Скрипт для поиска ученика @AlenaSaintly
"""

import sqlite3
import os

def find_alena_student():
    """Ищет ученика @AlenaSaintly"""
    
    current_dir = os.path.dirname(os.path.abspath(__file__))
    shared_db = os.path.join(current_dir, "shared", "test_answers.db")
    
    print("🔍 Поиск ученика @AlenaSaintly")
    print("=" * 50)
    print(f"📁 База данных: {shared_db}")
    
    try:
        with sqlite3.connect(shared_db) as conn:
            cur = conn.cursor()
            
            # Ищем в user_profiles
            print("\n📋 Поиск в user_profiles:")
            print("-" * 40)
            
            cur.execute("""
                SELECT user_id, username, full_name 
                FROM user_profiles 
                WHERE username LIKE '%alena%' OR username LIKE '%saintly%' 
                   OR full_name LIKE '%Алена%' OR full_name LIKE '%Елена%'
                   OR full_name LIKE '%Королев%' OR full_name LIKE '%Алексей%'
            """)
            rows = cur.fetchall()
            
            print(f"👥 Найдено в user_profiles: {len(rows)}")
            for user_id, username, full_name in rows:
                print(f"   ID: {user_id}, Username: {username}, Имя: {full_name}")
            
            # Ищем в test_answers
            print("\n📋 Поиск в test_answers:")
            print("-" * 40)
            
            cur.execute("""
                SELECT DISTINCT user_id, username, full_name 
                FROM test_answers 
                WHERE username LIKE '%alena%' OR username LIKE '%saintly%'
                   OR full_name LIKE '%Алена%' OR full_name LIKE '%Елена%'
                   OR full_name LIKE '%Королев%' OR full_name LIKE '%Алексей%'
            """)
            rows = cur.fetchall()
            
            print(f"📝 Найдено в test_answers: {len(rows)}")
            for user_id, username, full_name in rows:
                print(f"   ID: {user_id}, Username: {username}, Имя: {full_name}")
            
            # Проверяем всех учеников с групповым доступом
            print("\n📋 Ученики с групповым доступом:")
            print("-" * 40)
            
            cur.execute("""
                SELECT user_id FROM teacher_groups
            """)
            group_users = cur.fetchall()
            
            print(f"👥 Всего учеников в группе: {len(group_users)}")
            for (user_id,) in group_users:
                # Получаем информацию об ученике
                cur.execute("""
                    SELECT username, full_name FROM user_profiles WHERE user_id = ?
                """, (user_id,))
                profile = cur.fetchone()
                
                if profile:
                    username, full_name = profile
                    print(f"   ID: {user_id}, Username: {username}, Имя: {full_name}")
                else:
                    print(f"   ID: {user_id}, Информация не найдена")
                    
    except Exception as e:
        print(f"❌ Ошибка: {e}")

if __name__ == "__main__":
    find_alena_student()

