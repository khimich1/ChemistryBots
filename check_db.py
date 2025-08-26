#!/usr/bin/env python3
"""
Скрипт для проверки содержимого базы данных
"""

import sqlite3
import os

def check_database():
    """Проверяет содержимое базы данных"""
    
    current_dir = os.path.dirname(os.path.abspath(__file__))
    prepod_db = os.path.join(current_dir, "prepod_bot", "test_answers.db")
    
    print("🔍 Проверка базы данных")
    print("=" * 50)
    print(f"📁 База данных: {prepod_db}")
    print(f"📁 Существует: {'✅' if os.path.exists(prepod_db) else '❌'}")
    
    if not os.path.exists(prepod_db):
        print("❌ База данных не найдена!")
        return
    
    try:
        with sqlite3.connect(prepod_db) as conn:
            cur = conn.cursor()
            
            # Проверяем таблицу user_profiles
            print("\n📋 Таблица user_profiles:")
            print("-" * 40)
            
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_profiles'")
            if cur.fetchone():
                cur.execute("SELECT user_id, username, full_name FROM user_profiles")
                rows = cur.fetchall()
                
                if rows:
                    for user_id, username, full_name in rows:
                        print(f"👤 ID: {user_id}, Username: {username}, Name: {full_name}")
                else:
                    print("❌ Таблица пуста")
            else:
                print("❌ Таблица не существует")
            
            # Проверяем таблицу test_answers
            print("\n📋 Таблица test_answers:")
            print("-" * 40)
            
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='test_answers'")
            if cur.fetchone():
                cur.execute("SELECT DISTINCT user_id, username, full_name FROM test_answers LIMIT 5")
                rows = cur.fetchall()
                
                if rows:
                    for user_id, username, full_name in rows:
                        print(f"👤 ID: {user_id}, Username: {username}, Name: {full_name}")
                    print(f"... и еще {len(rows)} записей")
                else:
                    print("❌ Таблица пуста")
            else:
                print("❌ Таблица не существует")
                
    except Exception as e:
        print(f"❌ Ошибка: {e}")

if __name__ == "__main__":
    check_database()
