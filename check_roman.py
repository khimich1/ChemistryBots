#!/usr/bin/env python3
"""
Скрипт для проверки Смирнова Романа
"""

import sqlite3
import os

def check_roman():
    """Проверяет Смирнова Романа"""
    
    current_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Проверяем в prepod_bot базе
    shared_db = os.path.join(current_dir, "shared", "test_answers.db")
    govr_db = os.path.join(current_dir, "govr_bot", "bot", "services", "answers.db")
    
    print("🔍 Проверка Смирнова Романа")
    print("=" * 50)
    
    # Ищем Смирнова Романа в prepod_bot
    print("📋 Поиск в prepod_bot базе:")
    print("-" * 40)
    
    if os.path.exists(shared_db):
        try:
            with sqlite3.connect(shared_db) as conn:
                cur = conn.cursor()
                
                # Ищем в user_profiles
                cur.execute("""
                    SELECT user_id, username, full_name 
                    FROM user_profiles 
                    WHERE full_name LIKE '%Смирнов%' OR full_name LIKE '%Роман%'
                """)
                rows = cur.fetchall()
                
                print(f"👥 Найдено в user_profiles: {len(rows)}")
                for user_id, username, full_name in rows:
                    print(f"   ID: {user_id}, Username: {username}, Имя: {full_name}")
                
                # Ищем в test_answers
                cur.execute("""
                    SELECT DISTINCT user_id, username, full_name 
                    FROM test_answers 
                    WHERE full_name LIKE '%Смирнов%' OR full_name LIKE '%Роман%'
                """)
                rows = cur.fetchall()
                
                print(f"📝 Найдено в test_answers: {len(rows)}")
                for user_id, username, full_name in rows:
                    print(f"   ID: {user_id}, Username: {username}, Имя: {full_name}")
                    
        except Exception as e:
            print(f"❌ Ошибка при проверке prepod_bot: {e}")
    else:
        print("❌ База prepod_bot не найдена")
    
    # Проверяем в govr_bot базе
    print("\n📋 Поиск в govr_bot базе:")
    print("-" * 40)
    
    if os.path.exists(govr_db):
        try:
            with sqlite3.connect(govr_db) as conn:
                cur = conn.cursor()
                
                # Проверяем таблицу user_plans
                cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_plans'")
                if cur.fetchone():
                    cur.execute("SELECT user_id, plan_code FROM user_plans")
                    rows = cur.fetchall()
                    
                    print(f"📊 Всего тарифов в govr_bot: {len(rows)}")
                    for user_id, plan_code in rows:
                        print(f"   ID: {user_id}, План: {plan_code}")
                        
                        # Если это групповой план, проверяем одобрение
                        if plan_code == 'group':
                            print(f"      🔍 Проверяем одобрение для ID {user_id}...")
                            
                            # Импортируем функцию проверки
                            import sys
                            govr_path = os.path.join(current_dir, "govr_bot")
                            sys.path.append(govr_path)
                            
                            try:
                                from bot.services.teacher_access import is_student_approved_by_teacher
                                is_approved = is_student_approved_by_teacher(user_id)
                                print(f"      ✅ Одобрен преподавателем: {'Да' if is_approved else 'Нет'}")
                            except Exception as e:
                                print(f"      ❌ Ошибка проверки: {e}")
                else:
                    print("❌ Таблица user_plans не существует")
                    
        except Exception as e:
            print(f"❌ Ошибка при проверке govr_bot: {e}")
    else:
        print("❌ База govr_bot не найдена")

if __name__ == "__main__":
    check_roman()
