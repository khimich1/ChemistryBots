#!/usr/bin/env python3
"""
Отладочный скрипт для проверки подключения к базе данных
"""

import sqlite3
import os

def debug_db_connection():
    """Отлаживает подключение к базе данных"""
    
    current_dir = os.path.dirname(os.path.abspath(__file__))
    prepod_db = os.path.join(current_dir, "prepod_bot", "test_answers.db")
    
    print("🔍 Отладка подключения к базе данных")
    print("=" * 50)
    print(f"📁 Путь к базе: {prepod_db}")
    print(f"📁 Существует: {'✅' if os.path.exists(prepod_db) else '❌'}")
    
    if not os.path.exists(prepod_db):
        print("❌ База данных не найдена!")
        return
    
    try:
        with sqlite3.connect(prepod_db) as conn:
            cur = conn.cursor()
            
            # Проверяем таблицу user_profiles
            print("\n📋 Проверка таблицы user_profiles:")
            print("-" * 40)
            
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_profiles'")
            if cur.fetchone():
                print("✅ Таблица user_profiles существует")
                
                # Получаем все записи
                cur.execute("SELECT user_id, username, full_name FROM user_profiles")
                rows = cur.fetchall()
                
                print(f"📊 Всего записей: {len(rows)}")
                for user_id, username, full_name in rows:
                    print(f"👤 ID: {user_id}, Username: {username}, Name: {full_name}")
            else:
                print("❌ Таблица user_profiles не существует")
                
    except Exception as e:
        print(f"❌ Ошибка: {e}")

if __name__ == "__main__":
    debug_db_connection()
