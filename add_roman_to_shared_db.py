#!/usr/bin/env python3
"""
Скрипт для добавления группового тарифа Смирнову Роману в shared базу данных
"""

import sqlite3
import os

def add_roman_to_shared_db():
    """Добавляет групповой тариф Смирнову Роману в shared базу данных"""
    
    current_dir = os.path.dirname(os.path.abspath(__file__))
    shared_db = os.path.join(current_dir, "shared", "test_answers.db")
    
    roman_id = 727117860  # ID Смирнова Романа
    
    print("👤 Добавление группового тарифа Смирнову Роману в shared базу")
    print("=" * 60)
    print(f"📁 База shared: {shared_db}")
    print(f"📁 Существует: {'✅' if os.path.exists(shared_db) else '❌'}")
    print(f"👤 ID Смирнова Романа: {roman_id}")
    
    try:
        with sqlite3.connect(shared_db) as conn:
            cur = conn.cursor()
            
            # Создаем таблицу user_plans, если её нет
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_plans(
                    user_id INTEGER PRIMARY KEY,
                    plan_code TEXT,
                    started_at TEXT
                )
            """)
            
            # Добавляем групповой тариф Смирнову Роману
            cur.execute("""
                INSERT OR REPLACE INTO user_plans (user_id, plan_code, started_at)
                VALUES (?, ?, datetime('now'))
            """, (roman_id, 'group'))
            
            conn.commit()
            print(f"✅ Добавлен групповой тариф Смирнову Роману (ID: {roman_id})")
            
            # Проверяем, что тариф добавлен
            cur.execute("SELECT plan_code FROM user_plans WHERE user_id = ?", (roman_id,))
            row = cur.fetchone()
            
            if row:
                print(f"📊 Текущий тариф: {row[0]}")
            else:
                print("❌ Тариф не найден")
                
    except Exception as e:
        print(f"❌ Ошибка: {e}")

if __name__ == "__main__":
    add_roman_to_shared_db()

